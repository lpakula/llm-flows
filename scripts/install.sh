#!/usr/bin/env bash
set -euo pipefail

# llmflows installation script
# Usage: curl -fsSL --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash

BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MUTED='\033[2m'
NC='\033[0m'

VERBOSE="${LLMFLOWS_VERBOSE:-0}"
NO_PROMPT="${LLMFLOWS_NO_PROMPT:-0}"
DRY_RUN="${LLMFLOWS_DRY_RUN:-0}"
HELP=0

TMPFILES=()
cleanup_tmpfiles() {
    local f
    for f in "${TMPFILES[@]:-}"; do
        rm -rf "$f" 2>/dev/null || true
    done
}
trap cleanup_tmpfiles EXIT

mktempfile() {
    local f
    f="$(mktemp)"
    TMPFILES+=("$f")
    echo "$f"
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_info() {
    echo -e "${BLUE}==> ${NC}$*"
}

log_success() {
    echo -e "${GREEN}✓${NC}  $*"
}

log_warning() {
    echo -e "${YELLOW}!${NC}  $*"
}

log_error() {
    echo -e "${RED}✗${NC}  $*" >&2
}

log_muted() {
    echo -e "${MUTED}$*${NC}"
}

STAGE_CURRENT=0
STAGE_TOTAL=5

log_stage() {
    STAGE_CURRENT=$((STAGE_CURRENT + 1))
    echo ""
    echo -e "${BLUE}${BOLD}[${STAGE_CURRENT}/${STAGE_TOTAL}] $*${NC}"
}

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
print_usage() {
    cat <<EOF
llmflows installer (macOS + Linux)

Usage:
  curl -fsSL --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
  curl ... | bash -s -- [options]

Options:
  --verbose        Print debug output
  --no-prompt      Disable interactive prompts (for CI)
  --dry-run        Print what would happen, no changes
  --help, -h       Show this help

Environment variables:
  LLMFLOWS_VERBOSE=1       Same as --verbose
  LLMFLOWS_NO_PROMPT=1     Same as --no-prompt
  LLMFLOWS_DRY_RUN=1       Same as --dry-run

Examples:
  curl -fsSL --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
  curl ... | bash -s -- --verbose
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --verbose)   VERBOSE=1; shift ;;
            --no-prompt) NO_PROMPT=1; shift ;;
            --dry-run)   DRY_RUN=1; shift ;;
            --help|-h)   HELP=1; shift ;;
            *)           shift ;;
        esac
    done
}

configure_verbose() {
    if [[ "$VERBOSE" == "1" ]]; then
        set -x
    fi
}

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------
OS="unknown"

detect_os() {
    if [[ "${OSTYPE:-}" == "darwin"* ]]; then
        OS="macos"
    elif [[ "${OSTYPE:-}" == "linux-gnu"* ]] || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
        OS="linux"
    fi

    if [[ "$OS" == "unknown" ]]; then
        log_error "Unsupported operating system: ${OSTYPE:-unknown}"
        echo "This installer supports macOS and Linux (including WSL)."
        exit 1
    fi

    log_success "Detected OS: $OS"
}

# ---------------------------------------------------------------------------
# Privilege helpers
# ---------------------------------------------------------------------------
is_root() {
    [[ "$(id -u)" -eq 0 ]]
}

require_sudo() {
    if [[ "$OS" != "linux" ]]; then
        return 0
    fi
    if is_root; then
        return 0
    fi
    if command -v sudo &>/dev/null; then
        if ! sudo -n true >/dev/null 2>&1; then
            log_info "Administrator privileges required; enter your password"
            sudo -v
        fi
        return 0
    fi
    log_error "sudo is required for system installs on Linux"
    echo "  Install sudo or re-run as root."
    exit 1
}

# ---------------------------------------------------------------------------
# Homebrew (macOS)
# ---------------------------------------------------------------------------
resolve_brew_bin() {
    local brew_bin=""
    brew_bin="$(command -v brew 2>/dev/null || true)"
    if [[ -n "$brew_bin" ]]; then
        echo "$brew_bin"
        return 0
    fi
    if [[ -x "/opt/homebrew/bin/brew" ]]; then
        echo "/opt/homebrew/bin/brew"
        return 0
    fi
    if [[ -x "/usr/local/bin/brew" ]]; then
        echo "/usr/local/bin/brew"
        return 0
    fi
    return 1
}

activate_brew_for_session() {
    local brew_bin=""
    brew_bin="$(resolve_brew_bin || true)"
    if [[ -z "$brew_bin" ]]; then
        return 1
    fi
    eval "$("$brew_bin" shellenv 2>/dev/null)" || true
    return 0
}

refresh_shell_command_cache() {
    hash -r 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Download helper (curl with retry, wget fallback)
# ---------------------------------------------------------------------------
download_file() {
    local url="$1"
    local output="$2"

    if command -v curl &>/dev/null; then
        curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --retry-delay 1 --retry-connrefused -o "$output" "$url"
        return
    fi
    if command -v wget &>/dev/null; then
        wget -q --https-only --tries=3 --timeout=20 -O "$output" "$url"
        return
    fi
    log_error "Neither curl nor wget found — cannot download"
    exit 1
}

# ---------------------------------------------------------------------------
# run_quiet_step: run a command, capture output, show on failure
# ---------------------------------------------------------------------------
run_quiet_step() {
    local title="$1"
    shift

    if [[ "$VERBOSE" == "1" ]]; then
        log_info "$title"
        "$@"
        return $?
    fi

    local log
    log="$(mktempfile)"
    if "$@" >"$log" 2>&1; then
        return 0
    fi

    log_error "${title} failed"
    if [[ -s "$log" ]]; then
        tail -n 40 "$log" >&2 || true
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Python detection & installation
# ---------------------------------------------------------------------------
PYTHON_CMD=""
PYTHON_VERSION=""

find_python() {
    local cmd=""
    local version="" major="" minor=""

    for candidate in python3 python; do
        cmd="$(command -v "$candidate" 2>/dev/null || true)"
        if [[ -z "$cmd" ]]; then
            continue
        fi

        version="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'  2>/dev/null || true)"
        if [[ -z "$version" ]]; then
            continue
        fi

        major="${version%%.*}"
        minor="${version#*.}"
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON_CMD="$cmd"
            PYTHON_VERSION="$version"
            return 0
        fi
    done

    return 1
}

install_python_linux() {
    require_sudo

    if command -v apt-get &>/dev/null; then
        if is_root; then
            run_quiet_step "Updating package index" apt-get update -qq
            run_quiet_step "Installing Python" apt-get install -y -qq python3 python3-pip python3-venv
        else
            run_quiet_step "Updating package index" sudo apt-get update -qq
            run_quiet_step "Installing Python" sudo apt-get install -y -qq python3 python3-pip python3-venv
        fi
        return 0
    fi

    if command -v dnf &>/dev/null; then
        if is_root; then
            run_quiet_step "Installing Python" dnf install -y -q python3 python3-pip
        else
            run_quiet_step "Installing Python" sudo dnf install -y -q python3 python3-pip
        fi
        return 0
    fi

    if command -v yum &>/dev/null; then
        if is_root; then
            run_quiet_step "Installing Python" yum install -y -q python3 python3-pip
        else
            run_quiet_step "Installing Python" sudo yum install -y -q python3 python3-pip
        fi
        return 0
    fi

    if command -v apk &>/dev/null; then
        if is_root; then
            run_quiet_step "Installing Python" apk add --no-cache python3 py3-pip
        else
            run_quiet_step "Installing Python" sudo apk add --no-cache python3 py3-pip
        fi
        return 0
    fi

    return 1
}

check_python() {
    log_info "Checking Python..."

    if find_python; then
        log_success "Python ${PYTHON_VERSION} found (${PYTHON_CMD})"
        return 0
    fi

    log_info "Python 3.11+ not found, attempting install"

    if [[ "$OS" == "macos" ]]; then
        local brew_bin=""
        brew_bin="$(resolve_brew_bin || true)"
        if [[ -n "$brew_bin" ]]; then
            activate_brew_for_session || true
            run_quiet_step "Installing Python via Homebrew" "$brew_bin" install python@3.12
            refresh_shell_command_cache
        else
            log_error "Homebrew not found — cannot auto-install Python"
            echo ""
            echo "Install Homebrew first:"
            echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            echo ""
            echo "Or install Python 3.11+ manually from https://python.org"
            exit 1
        fi
    elif [[ "$OS" == "linux" ]]; then
        if ! install_python_linux; then
            log_error "Could not auto-install Python"
            echo ""
            echo "Install Python 3.11+ manually:"
            echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
            echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
            echo "  Download from: https://python.org"
            exit 1
        fi
    fi

    refresh_shell_command_cache

    if ! find_python; then
        log_error "Python 3.11+ is required but could not be found after install"
        echo ""
        echo "Install Python 3.11+ manually:"
        echo "  macOS:          brew install python@3.12"
        echo "  Ubuntu/Debian:  sudo apt install python3 python3-pip python3-venv"
        echo "  Download from:  https://python.org"
        exit 1
    fi

    log_success "Python ${PYTHON_VERSION} installed (${PYTHON_CMD})"
}

# ---------------------------------------------------------------------------
# uv — preferred installer (fast, no PEP 668 issues)
# ---------------------------------------------------------------------------
UV_CMD=""

install_uv() {
    log_info "Installing uv..."

    if [[ "$OS" == "macos" ]]; then
        local brew_bin=""
        brew_bin="$(resolve_brew_bin || true)"
        if [[ -n "$brew_bin" ]]; then
            activate_brew_for_session || true
            if run_quiet_step "Installing uv via Homebrew" "$brew_bin" install uv; then
                refresh_shell_command_cache
                UV_CMD="$(command -v uv 2>/dev/null || true)"
                if [[ -n "$UV_CMD" ]]; then
                    log_success "uv installed via Homebrew"
                    return 0
                fi
            fi
        fi
    fi

    local tmp
    tmp="$(mktempfile)"
    if download_file "https://astral.sh/uv/install.sh" "$tmp"; then
        if run_quiet_step "Installing uv via official installer" bash "$tmp"; then
            export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
            refresh_shell_command_cache
            UV_CMD="$(command -v uv 2>/dev/null || true)"
            if [[ -n "$UV_CMD" ]]; then
                log_success "uv installed via official installer"
                return 0
            fi
        fi
    fi

    return 1
}

check_uv() {
    UV_CMD="$(command -v uv 2>/dev/null || true)"
    if [[ -n "$UV_CMD" ]]; then
        log_success "uv found ($UV_CMD)"
        return 0
    fi

    if install_uv; then
        return 0
    fi

    log_info "uv not available — will try pipx"
    return 1
}

# ---------------------------------------------------------------------------
# pipx — fallback installer
# ---------------------------------------------------------------------------
PIPX_CMD=""

check_pipx() {
    PIPX_CMD="$(command -v pipx 2>/dev/null || true)"
    if [[ -n "$PIPX_CMD" ]]; then
        log_success "pipx found ($PIPX_CMD)"
        return 0
    fi

    log_info "Installing pipx..."

    if [[ "$OS" == "macos" ]]; then
        local brew_bin=""
        brew_bin="$(resolve_brew_bin || true)"
        if [[ -n "$brew_bin" ]]; then
            activate_brew_for_session || true
            if run_quiet_step "Installing pipx via Homebrew" "$brew_bin" install pipx; then
                refresh_shell_command_cache
                PIPX_CMD="$(command -v pipx 2>/dev/null || true)"
                if [[ -n "$PIPX_CMD" ]]; then
                    log_success "pipx installed via Homebrew"
                    return 0
                fi
            fi
        fi
    fi

    if [[ -n "$PYTHON_CMD" ]]; then
        if "$PYTHON_CMD" -m pip install --user pipx >/dev/null 2>&1; then
            "$PYTHON_CMD" -m pipx ensurepath >/dev/null 2>&1 || true
            export PATH="$HOME/.local/bin:$PATH"
            refresh_shell_command_cache
            PIPX_CMD="$(command -v pipx 2>/dev/null || true)"
            if [[ -n "$PIPX_CMD" ]]; then
                log_success "pipx installed"
                return 0
            fi
            PIPX_CMD="$PYTHON_CMD -m pipx"
            log_success "pipx installed (via python -m pipx)"
            return 0
        fi
    fi

    if [[ "$OS" == "linux" ]]; then
        require_sudo
        if command -v apt-get &>/dev/null; then
            if is_root; then
                run_quiet_step "Installing pipx" apt-get install -y -qq pipx
            else
                run_quiet_step "Installing pipx" sudo apt-get install -y -qq pipx
            fi
            refresh_shell_command_cache
            PIPX_CMD="$(command -v pipx 2>/dev/null || true)"
            if [[ -n "$PIPX_CMD" ]]; then
                log_success "pipx installed via apt"
                return 0
            fi
        fi
    fi

    log_error "Failed to install pipx"
    echo ""
    echo "Install manually:"
    echo "  macOS: brew install pipx"
    echo "  Linux: sudo apt install pipx  (or pip install --user pipx)"
    return 1
}

# ---------------------------------------------------------------------------
# Node.js detection & installation (needed for browser tools / Playwright)
# ---------------------------------------------------------------------------
NODE_CMD=""

find_node() {
    NODE_CMD="$(command -v node 2>/dev/null || true)"
    if [[ -n "$NODE_CMD" ]]; then
        return 0
    fi
    return 1
}

install_node() {
    if [[ "$OS" == "macos" ]]; then
        local brew_bin=""
        brew_bin="$(resolve_brew_bin || true)"
        if [[ -n "$brew_bin" ]]; then
            activate_brew_for_session || true
            run_quiet_step "Installing Node.js via Homebrew" "$brew_bin" install node
            refresh_shell_command_cache
        fi
    elif [[ "$OS" == "linux" ]]; then
        require_sudo
        if command -v apt-get &>/dev/null; then
            if is_root; then
                run_quiet_step "Installing Node.js" apt-get install -y -qq nodejs npm
            else
                run_quiet_step "Installing Node.js" sudo apt-get install -y -qq nodejs npm
            fi
        elif command -v dnf &>/dev/null; then
            if is_root; then
                run_quiet_step "Installing Node.js" dnf install -y -q nodejs npm
            else
                run_quiet_step "Installing Node.js" sudo dnf install -y -q nodejs npm
            fi
        fi
        refresh_shell_command_cache
    fi
}

check_node() {
    log_info "Checking Node.js..."

    if find_node; then
        local version=""
        version="$(node --version 2>/dev/null || true)"
        log_success "Node.js ${version} found"
        return 0
    fi

    log_info "Node.js not found, attempting install"
    install_node

    if find_node; then
        local version=""
        version="$(node --version 2>/dev/null || true)"
        log_success "Node.js ${version} installed"
        return 0
    fi

    log_warning "Node.js not found — browser tools will not be available"
    log_muted "  Install Node.js from https://nodejs.org to enable browser automation"
    return 1
}

# ---------------------------------------------------------------------------
# Node tool dependencies (installed to ~/.llmflows/node_modules/)
# ---------------------------------------------------------------------------
install_node_tools() {
    if ! command -v npm &>/dev/null; then
        log_warning "npm not found — skipping Node tool dependencies"
        return 1
    fi

    local tools_dir="$HOME/.llmflows"
    mkdir -p "$tools_dir"

    log_info "Installing Node tool dependencies to $tools_dir ..."

    if run_quiet_step "Installing Node packages" npm install --prefix "$tools_dir" playwright "@sinclair/typebox" tsx; then
        log_success "Node tool dependencies installed"
    else
        log_warning "Failed to install Node tool dependencies"
        log_muted "  Run manually: npm install --prefix ~/.llmflows playwright @sinclair/typebox tsx"
        return 1
    fi

    log_info "Downloading Chromium browser..."
    if run_quiet_step "Downloading Chromium" "$tools_dir/node_modules/.bin/playwright" install chromium; then
        log_success "Chromium browser downloaded"
        return 0
    fi

    log_warning "Failed to download Chromium — browser tools may not work"
    log_muted "  Run manually: ~/.llmflows/node_modules/.bin/playwright install chromium"
    return 1
}

# ---------------------------------------------------------------------------
# llmflows installation
# ---------------------------------------------------------------------------
REPO_URL="git+https://github.com/lpakula/llm-flows"

install_with_uv() {
    log_info "Installing llmflows via uv..."

    local log
    log="$(mktempfile)"

    if "$UV_CMD" tool install --force --from "$REPO_URL" llmflows >"$log" 2>&1; then
        log_success "llmflows installed via uv"
        return 0
    fi

    if [[ "$VERBOSE" == "1" && -s "$log" ]]; then
        log_warning "uv install attempt failed:"
        tail -n 40 "$log" >&2 || true
    fi

    log_info "Retrying uv install with --reinstall..."
    if "$UV_CMD" tool install --force --reinstall --from "$REPO_URL" llmflows >"$log" 2>&1; then
        log_success "llmflows installed via uv (retry)"
        return 0
    fi

    if [[ -s "$log" ]]; then
        log_warning "uv install failed:"
        tail -n 40 "$log" >&2 || true
    fi

    return 1
}

install_with_pipx() {
    log_info "Installing llmflows via pipx..."

    local log
    log="$(mktempfile)"

    local -a pipx_cmd
    if [[ "$PIPX_CMD" == *" "* ]]; then
        # "python3 -m pipx" style
        IFS=' ' read -ra pipx_cmd <<< "$PIPX_CMD"
    else
        pipx_cmd=("$PIPX_CMD")
    fi

    if "${pipx_cmd[@]}" install --force --pip-args="--no-cache-dir" "$REPO_URL" >"$log" 2>&1; then
        "${pipx_cmd[@]}" ensurepath >/dev/null 2>&1 || true
        log_success "llmflows installed via pipx"
        return 0
    fi

    if [[ "$VERBOSE" == "1" && -s "$log" ]]; then
        log_warning "pipx install attempt failed:"
        tail -n 40 "$log" >&2 || true
    fi

    log_info "Retrying pipx install..."
    if "${pipx_cmd[@]}" install --force --pip-args="--no-cache-dir" "$REPO_URL" >"$log" 2>&1; then
        "${pipx_cmd[@]}" ensurepath >/dev/null 2>&1 || true
        log_success "llmflows installed via pipx (retry)"
        return 0
    fi

    if [[ -s "$log" ]]; then
        log_warning "pipx install failed:"
        tail -n 40 "$log" >&2 || true
    fi

    return 1
}

install_llmflows() {
    if [[ -n "$UV_CMD" ]]; then
        if install_with_uv; then
            return 0
        fi
        log_warning "uv install failed — falling back to pipx"
    fi

    if [[ -z "$PIPX_CMD" ]]; then
        if ! check_pipx; then
            log_error "No package installer available (tried uv and pipx)"
            echo ""
            echo "Install manually:"
            echo "  uv tool install git+https://github.com/lpakula/llm-flows"
            echo "  # or"
            echo "  pipx install git+https://github.com/lpakula/llm-flows"
            exit 1
        fi
    fi

    if install_with_pipx; then
        return 0
    fi

    log_error "Failed to install llmflows"
    echo ""
    echo "Try installing manually:"
    echo "  uv tool install git+https://github.com/lpakula/llm-flows"
    echo "  # or"
    echo "  pipx install --force --pip-args=\"--no-cache-dir\" git+https://github.com/lpakula/llm-flows"
    exit 1
}

# ---------------------------------------------------------------------------
# PATH management
# ---------------------------------------------------------------------------
ensure_local_bin_on_path() {
    local target="$HOME/.local/bin"
    mkdir -p "$target"
    export PATH="$target:$PATH"

    local shell_profile=""
    if [[ -f "$HOME/.zshrc" ]]; then
        shell_profile="$HOME/.zshrc"
    elif [[ -f "$HOME/.bashrc" ]]; then
        shell_profile="$HOME/.bashrc"
    elif [[ -f "$HOME/.bash_profile" ]]; then
        shell_profile="$HOME/.bash_profile"
    fi

    if [[ -n "$shell_profile" ]]; then
        if ! grep -q '\.local/bin' "$shell_profile" 2>/dev/null; then
            echo '' >> "$shell_profile"
            echo '# Added by llmflows installer' >> "$shell_profile"
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$shell_profile"
            log_info "Added ~/.local/bin to PATH in $shell_profile"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
verify_installation() {
    log_info "Verifying installation..."

    ensure_local_bin_on_path
    refresh_shell_command_cache

    if command -v llmflows &>/dev/null; then
        local version=""
        version="$(llmflows --version 2>/dev/null || true)"
        if [[ -n "$version" ]]; then
            log_success "llmflows ${version} is installed and ready"
        else
            log_success "llmflows is installed and ready"
        fi
    else
        log_success "llmflows installed"
        log_warning "Restart your terminal or run: source ~/.zshrc (or ~/.bashrc)"
    fi

    echo ""
    echo "Get started:"
    echo "  cd your-folder"
    echo "  llmflows init"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    if [[ "$HELP" == "1" ]]; then
        print_usage
        return 0
    fi

    echo ""
    echo -e "${BOLD}llmflows Installer${NC}"
    echo ""

    detect_os

    if [[ "$DRY_RUN" == "1" ]]; then
        log_info "Dry run — showing install plan only"
        echo ""
        echo "  OS:              $OS"
        echo "  Python:          $(find_python 2>/dev/null && echo "$PYTHON_CMD ($PYTHON_VERSION)" || echo "will install")"
        echo "  Installer:       uv (preferred) or pipx (fallback)"
        echo "  Package:         git+https://github.com/lpakula/llm-flows"
        echo ""
        log_success "Dry run complete (no changes made)"
        return 0
    fi

    # Stage 1: Homebrew (macOS)
    log_stage "Preparing environment"

    if [[ "$OS" == "macos" ]]; then
        local brew_bin=""
        brew_bin="$(resolve_brew_bin || true)"
        if [[ -n "$brew_bin" ]]; then
            activate_brew_for_session || true
            log_success "Homebrew found"
        else
            log_info "Homebrew not found — installing"
            run_quiet_step "Installing Homebrew" bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            if ! activate_brew_for_session; then
                log_warning "Homebrew installed but not activated in this shell"
            else
                log_success "Homebrew installed"
            fi
        fi
    fi

    # Stage 2: Python
    log_stage "Checking Python"
    check_python

    # Stage 3: Package installer + llmflows
    log_stage "Installing llmflows"
    check_uv || true
    install_llmflows

    # Stage 4: Browser tools (Node.js + dependencies)
    log_stage "Setting up browser tools"
    if check_node; then
        install_node_tools || true
    fi

    # Stage 5: Verify
    log_stage "Verifying"
    verify_installation

    log_success "Installation complete!"
}

parse_args "$@"
configure_verbose
main
