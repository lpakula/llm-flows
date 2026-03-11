#!/usr/bin/env bash
#
# llmflows installation script
# Usage: curl -fsSL https://raw.githubusercontent.com/lpakula/llm-flows/main/scripts/install.sh | bash
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}==>${NC} $1"
}

log_success() {
    echo -e "${GREEN}==>${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}==>${NC} $1"
}

log_error() {
    echo -e "${RED}Error:${NC} $1" >&2
}

# Check Python version (requires 3.11+)
check_python() {
    log_info "Checking Python version..."
    
    local python_cmd=""
    
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        python_cmd="python3"
    elif command -v python &> /dev/null; then
        python_cmd="python"
    else
        log_error "Python is not installed"
        echo ""
        echo "Please install Python 3.11 or later:"
        echo "  - macOS: brew install python@3.11"
        echo "  - Ubuntu/Debian: sudo apt install python3.11"
        echo "  - Download from https://python.org"
        echo ""
        exit 1
    fi
    
    # Check version
    local version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major=$(echo "$version" | cut -d. -f1)
    local minor=$(echo "$version" | cut -d. -f2)
    
    if [ "$major" -lt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -lt 11 ]); then
        log_error "Python 3.11 or later is required (found: $version)"
        echo ""
        echo "Please upgrade Python:"
        echo "  - macOS: brew install python@3.11"
        echo "  - Ubuntu/Debian: sudo apt install python3.11"
        echo "  - Download from https://python.org"
        echo ""
        exit 1
    fi
    
    log_success "Python $version detected"
    echo "$python_cmd"
}

# Check/install pipx
ensure_pipx() {
    local python_cmd=$1
    
    if command -v pipx &> /dev/null; then
        log_success "pipx is already installed"
        return 0
    fi
    
    log_info "Installing pipx..."
    
    # On macOS, use brew (required due to PEP 668)
    if [[ "$(uname -s)" == "Darwin" ]]; then
        if command -v brew &> /dev/null; then
            if brew install pipx &> /dev/null; then
                log_success "pipx installed via brew"
                return 0
            fi
        else
            log_error "Homebrew is required on macOS"
            echo ""
            echo "Install Homebrew first:"
            echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            echo ""
            echo "Then run this script again."
            exit 1
        fi
    fi
    
    # Try pip install --user (works on Linux)
    if $python_cmd -m pip install --user pipx &> /dev/null; then
        $python_cmd -m pipx ensurepath &> /dev/null || true
        log_success "pipx installed"
        
        if [ -f "$HOME/.bashrc" ]; then
            source "$HOME/.bashrc" 2>/dev/null || true
        fi
        if [ -f "$HOME/.zshrc" ]; then
            source "$HOME/.zshrc" 2>/dev/null || true
        fi
        
        return 0
    fi
    
    log_error "Failed to install pipx"
    echo ""
    echo "Install pipx manually:"
    echo "  - macOS: brew install pipx"
    echo "  - Linux: sudo apt install pipx"
    echo ""
    exit 1
}

# Install llmflows
install_llmflows() {
    local python_cmd=$1
    
    log_info "Installing llmflows..."
    
    # Try pipx first (--force to upgrade, --no-cache-dir for fresh install)
    if command -v pipx &> /dev/null; then
        if pipx install --force --pip-args="--no-cache-dir" git+https://github.com/lpakula/llm-flows 2>/dev/null; then
            pipx ensurepath &> /dev/null || true
            return 0
        fi
    fi
    
    # Fallback to python -m pipx
    if $python_cmd -m pipx install --force --pip-args="--no-cache-dir" git+https://github.com/lpakula/llm-flows; then
        $python_cmd -m pipx ensurepath &> /dev/null || true
        return 0
    fi
    
    log_error "Failed to install llmflows"
    echo ""
    echo "Try installing manually:"
    echo "  pipx install --force --pip-args=\"--no-cache-dir\" git+https://github.com/lpakula/llm-flows"
    echo ""
    exit 1
}

# Verify installation
verify_installation() {
    log_info "Verifying installation..."
    
    # Ensure ~/.local/bin is in PATH for this session
    export PATH="$PATH:$HOME/.local/bin"
    
    # Add to shell profile if not already there
    local shell_profile=""
    if [ -f "$HOME/.zshrc" ]; then
        shell_profile="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        shell_profile="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        shell_profile="$HOME/.bash_profile"
    fi
    
    local path_added=false
    if [ -n "$shell_profile" ]; then
        if ! grep -q 'export PATH=.*\.local/bin' "$shell_profile" 2>/dev/null; then
            echo '' >> "$shell_profile"
            echo '# Added by llmflows CLI installer' >> "$shell_profile"
            echo 'export PATH="$PATH:$HOME/.local/bin"' >> "$shell_profile"
            log_info "Added ~/.local/bin to PATH in $shell_profile"
            path_added=true
        fi
    fi
    
    # Check if llmflows is in PATH
    if command -v llmflows &> /dev/null; then
        log_success "llmflows is installed and ready!"
    else
        log_success "llmflows installed successfully!"
    fi
    
    echo ""
    if [ "$path_added" = true ]; then
        log_warning "⚠️  Restart your terminal for the 'llmflows' command to work"
        echo ""
    fi
    echo "Get started:"
    echo "  cd your-project"
    echo "  llmflows init"
    echo ""
}

# Main
main() {
    echo ""
    echo "llmflows Installer"
    echo ""
    
    # Check Python
    python_cmd=$(check_python)
    
    # Ensure pipx is installed
    ensure_pipx "$python_cmd"
    
    # Install llmflows
    install_llmflows "$python_cmd"
    
    # Verify
    verify_installation
    
    log_success "Installation complete!"
}

main "$@"
