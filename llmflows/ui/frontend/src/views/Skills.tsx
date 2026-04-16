import { useState, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/api/client";
import { useInterval } from "@/hooks/useInterval";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { SkillInfo } from "@/api/types";

function SkillPreviewModal({
  skill,
  spaceId,
  onClose,
}: {
  skill: SkillInfo;
  spaceId: string;
  onClose: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSkillContent(spaceId, skill.name)
      .then((res) => setContent(res.content))
      .catch(() => setContent("*Failed to load skill content.*"))
      .finally(() => setLoading(false));
  }, [spaceId, skill.name]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70" />
      <div
        className="relative bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
          <div>
            <h3 className="text-base font-mono font-semibold text-gray-100">{skill.name}</h3>
            <p className="text-[11px] text-gray-500 font-mono mt-0.5">{skill.path}</p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg leading-none px-2">
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <p className="text-sm text-gray-500 animate-pulse">Loading...</p>
          ) : content ? (
            <MarkdownContent text={content} className="text-sm" />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SkillCard({ skill, onClick }: { skill: SkillInfo; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-left hover:bg-gray-800/50 hover:border-gray-700 transition w-full"
    >
      <span className="text-sm font-mono font-medium text-gray-100">{skill.name}</span>
      {skill.description && (
        <p className="text-xs text-gray-400 leading-relaxed mt-1.5">{skill.description}</p>
      )}
      {skill.compatibility && (
        <p className="text-[11px] text-gray-500 mt-1 italic">{skill.compatibility}</p>
      )}
      <p className="text-[11px] text-gray-600 font-mono truncate mt-2">{skill.path}</p>
    </button>
  );
}

export function SkillsView() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [previewSkill, setPreviewSkill] = useState<SkillInfo | null>(null);

  const load = useCallback(async () => {
    if (!spaceId) return;
    try {
      const sk = await api.listSkills(spaceId);
      setSkills(sk);
    } catch (e) {
      console.error("Skills load error:", e);
    }
  }, [spaceId]);

  useEffect(() => { load(); }, [load]);
  useInterval(load, 10000);

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div>
        <h2 className="text-xl font-semibold mb-1">Skills</h2>
        <p className="text-xs text-gray-500 mb-4">
          Discovered from <code className="text-gray-400">.agents/skills/</code> — {skills.length} found. Click to preview.
        </p>
        {skills.length === 0 ? (
          <p className="text-sm text-gray-600">No skills found.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {skills.map((s) => (
              <SkillCard key={s.name} skill={s} onClick={() => setPreviewSkill(s)} />
            ))}
          </div>
        )}
      </div>

      {previewSkill && spaceId && (
        <SkillPreviewModal
          skill={previewSkill}
          spaceId={spaceId}
          onClose={() => setPreviewSkill(null)}
        />
      )}
    </div>
  );
}
