#!/usr/bin/env python3
"""Sincroniza a fonte canônica em ai/ com OpenCode, Claude Code e Codex.

A fonte canônica é a única editável:

    ai/agents/<id>/agent.json + prompt.md
    ai/skills/<id>/SKILL.md (+ references/, scripts/, assets/)
    ai/flows/<id>/flow.json + FLOW.md
    ai/instructions/AGENTS.md

Os diretórios .opencode/, .claude/, .agents/ e .codex/ e os arquivos
AGENTS.md/CLAUDE.md são gerados. Não os edite à mão.

Agentes com mode direto também geram .codex/profiles/<id>.config.toml, que
ativa o perfil correspondente com `codex --profile <id>`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI_DIR = ROOT / "ai"
MANIFEST_NAME = ".generated.json"
GENERATED_COMMENT = "<!-- Gerado por scripts/sync_ai_assets.py. Edite a fonte em ai/. -->"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TARGETS = (".opencode", ".claude", ".agents", ".codex")
MODEL_TARGETS = ("opencode", "claude", "codex")
SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
SKIP_NAMES = {".DS_Store"}

KNOWN_TOOLS = {
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "shell",
    "webfetch",
    "websearch",
    "skill",
    "subagent",
}

OPENCODE_ACTIONS = {
    "read": "read",
    "write": "edit",
    "edit": "edit",
    "glob": "glob",
    "grep": "grep",
    "shell": "shell",
    "webfetch": "webfetch",
    "websearch": "websearch",
    "skill": "skill",
    "subagent": "subagent",
}

OPENCODE_ACTION_ORDER = (
    "read",
    "edit",
    "glob",
    "grep",
    "shell",
    "webfetch",
    "websearch",
    "skill",
    "subagent",
)

CLAUDE_TOOLS = {
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "glob": "Glob",
    "grep": "Grep",
    "shell": "Bash",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
    "skill": "Skill",
    "subagent": "Agent",
}

COLOR_HEX = {
    "red": "#ef4444",
    "blue": "#3b82f6",
    "green": "#22c55e",
    "yellow": "#eab308",
    "purple": "#8b5cf6",
    "orange": "#f59e0b",
    "pink": "#ec4899",
    "cyan": "#06b6d4",
}

REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
AGENT_MODES = ("direct", "subagent")
OPENCODE_MODES = {
    ("direct",): "primary",
    ("subagent",): "subagent",
    ("direct", "subagent"): "all",
}


class SyncError(Exception):
    """Erro de validação ou de layout da fonte canônica."""


@dataclass(frozen=True)
class Agent:
    name: str
    description: str
    modes: tuple[str, ...]
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    color: str | None
    models: dict[str, str | None]
    reasoning_effort: str | None
    prompt: str


@dataclass(frozen=True)
class Skill:
    name: str
    directory: Path


@dataclass(frozen=True)
class Flow:
    name: str
    display_name: str
    description: str
    argument_hint: str | None
    body: str


@dataclass
class Plan:
    files: dict[str, tuple[bytes, int]] = field(default_factory=dict)
    managed: dict[str, list[str]] = field(default_factory=lambda: {t: [] for t in TARGETS})

    def add(self, target: str, relpath: str, data: bytes, mode: int = 0o644) -> None:
        full = f"{target}/{relpath}"
        if full in self.files:
            raise SyncError(f"arquivo gerado duas vezes: {full}")
        self.files[full] = (data, mode)
        self.managed[target].append(relpath)


# ---------------------------------------------------------------------------
# Parsing e validação
# ---------------------------------------------------------------------------


def read_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    """Lê apenas campos de primeiro nível do frontmatter.

    A fonte canônica usa uma descrição de uma linha. Não é um parser YAML
    completo; é intencional para manter o gerador sem dependências.
    """

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SyncError(f"{path}: frontmatter deve começar na primeira linha com '---'")

    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise SyncError(f"{path}: frontmatter sem fechamento '---'")

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw = value.strip()
        if raw in {">", ">-", "|", "|-"}:
            raise SyncError(f"{path}: '{key.strip()}' deve ser uma única linha")
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        fields[key.strip()] = raw
    return fields, "\n".join(lines[end + 1 :])


def validate_name(name: str, directory: Path, kind: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise SyncError(f"{directory}: {kind} inválido '{name}' (use kebab-case minúsculo)")
    if name != directory.name:
        raise SyncError(
            f"{directory}: nome '{name}' deve ser igual ao diretório '{directory.name}'"
        )


def parse_modes(raw: object, meta_path: Path) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise SyncError(f"{meta_path}: 'modes' deve ser uma lista não vazia")

    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SyncError(f"{meta_path}: 'modes' deve conter apenas strings")
        values.append(item)

    unknown = set(values) - set(AGENT_MODES)
    if unknown:
        raise SyncError(f"{meta_path}: modos desconhecidos: {sorted(unknown)}")
    if len(set(values)) != len(values):
        raise SyncError(f"{meta_path}: 'modes' contém duplicatas")

    return tuple(mode for mode in AGENT_MODES if mode in set(values))


def validate_skills(root: Path) -> list[Skill]:
    skills_dir = root / "ai" / "skills"
    if not skills_dir.is_dir():
        raise SyncError(f"diretório não encontrado: {skills_dir}")

    skills: list[Skill] = []
    seen: set[str] = set()
    for directory in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
        skill_md = directory / "SKILL.md"
        if not skill_md.is_file():
            raise SyncError(f"{directory}: SKILL.md não encontrado")
        fields, _ = read_frontmatter(skill_md)
        name = fields.get("name", "")
        description = fields.get("description", "")
        validate_name(name, directory, "nome de skill")
        if not description:
            raise SyncError(f"{skill_md}: 'description' é obrigatório")
        if len(description) > 1024:
            raise SyncError(f"{skill_md}: 'description' excede 1024 caracteres")
        if name in seen:
            raise SyncError(f"{skill_md}: skill duplicada '{name}'")
        seen.add(name)
        skills.append(Skill(name=name, directory=directory))
    if not skills:
        raise SyncError(f"nenhuma skill encontrada em {skills_dir}")
    return skills


def load_agents(root: Path) -> list[Agent]:
    agents_dir = root / "ai" / "agents"
    if not agents_dir.is_dir():
        raise SyncError(f"diretório não encontrado: {agents_dir}")

    skill_ids = {skill.name for skill in validate_skills(root)}
    agents: list[Agent] = []
    seen: set[str] = set()

    for directory in sorted(path for path in agents_dir.iterdir() if path.is_dir()):
        meta_path = directory / "agent.json"
        prompt_path = directory / "prompt.md"
        if not meta_path.is_file() or not prompt_path.is_file():
            raise SyncError(f"{directory}: esperado agent.json e prompt.md")

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SyncError(f"{meta_path}: JSON inválido: {exc}") from exc
        if not isinstance(meta, dict):
            raise SyncError(f"{meta_path}: esperado um objeto JSON")

        name = str(meta.get("name", ""))
        validate_name(name, directory, "nome de agente")
        if name in seen:
            raise SyncError(f"{meta_path}: agente duplicado '{name}'")
        seen.add(name)

        description = str(meta.get("description", ""))
        if not description:
            raise SyncError(f"{meta_path}: 'description' é obrigatório")
        if len(description) > 1024:
            raise SyncError(f"{meta_path}: 'description' excede 1024 caracteres")

        modes = parse_modes(meta.get("modes"), meta_path)

        raw_tools = meta.get("tools", [])
        if not isinstance(raw_tools, list) or not raw_tools:
            raise SyncError(f"{meta_path}: 'tools' deve ser uma lista não vazia")
        tools = tuple(str(tool) for tool in raw_tools)
        unknown = set(tools) - KNOWN_TOOLS
        if unknown:
            raise SyncError(f"{meta_path}: ferramentas desconhecidas: {sorted(unknown)}")
        if len(set(tools)) != len(tools):
            raise SyncError(f"{meta_path}: 'tools' contém duplicatas")

        raw_skills = meta.get("skills", [])
        if not isinstance(raw_skills, list):
            raise SyncError(f"{meta_path}: 'skills' deve ser uma lista")
        skills = tuple(str(skill) for skill in raw_skills)
        missing = set(skills) - skill_ids
        if missing:
            raise SyncError(f"{meta_path}: skills inexistentes: {sorted(missing)}")

        color = meta.get("color")
        if color is not None and color not in COLOR_HEX:
            raise SyncError(f"{meta_path}: cor inválida '{color}'")

        raw_models = meta.get("models", {})
        if not isinstance(raw_models, dict):
            raise SyncError(f"{meta_path}: 'models' deve ser um objeto")
        unknown_targets = set(raw_models) - set(MODEL_TARGETS)
        if unknown_targets:
            raise SyncError(
                f"{meta_path}: alvos de modelo desconhecidos: {sorted(unknown_targets)}"
            )
        models: dict[str, str | None] = {}
        for target in MODEL_TARGETS:
            value = raw_models.get(target)
            if value is not None and not isinstance(value, str):
                raise SyncError(f"{meta_path}: models.{target} deve ser string ou null")
            models[target] = value

        effort = meta.get("reasoning_effort")
        if effort is not None and effort not in REASONING_EFFORTS:
            raise SyncError(f"{meta_path}: reasoning_effort inválido '{effort}'")

        prompt = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise SyncError(f"{prompt_path}: prompt vazio")

        agents.append(
            Agent(
                name=name,
                description=description,
                modes=modes,
                tools=tools,
                skills=skills,
                color=str(color) if color is not None else None,
                models=models,
                reasoning_effort=str(effort) if effort is not None else None,
                prompt=prompt,
            )
        )

    if not agents:
        raise SyncError(f"nenhum agente encontrado em {agents_dir}")
    return agents


def load_flows(root: Path) -> list[Flow]:
    flows_dir = root / "ai" / "flows"
    if not flows_dir.is_dir():
        raise SyncError(f"diretório não encontrado: {flows_dir}")

    flows: list[Flow] = []
    seen: set[str] = set()
    for directory in sorted(path for path in flows_dir.iterdir() if path.is_dir()):
        meta_path = directory / "flow.json"
        body_path = directory / "FLOW.md"
        if not meta_path.is_file() or not body_path.is_file():
            raise SyncError(f"{directory}: esperado flow.json e FLOW.md")

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SyncError(f"{meta_path}: JSON inválido: {exc}") from exc
        if not isinstance(meta, dict):
            raise SyncError(f"{meta_path}: esperado um objeto JSON")

        name = str(meta.get("name", ""))
        validate_name(name, directory, "nome de fluxo")
        if not name.startswith("flow-"):
            raise SyncError(f"{meta_path}: fluxos devem começar com 'flow-'")
        if name in seen:
            raise SyncError(f"{meta_path}: fluxo duplicado '{name}'")
        seen.add(name)

        description = str(meta.get("description", ""))
        if not description:
            raise SyncError(f"{meta_path}: 'description' é obrigatório")
        if len(description) > 1024:
            raise SyncError(f"{meta_path}: 'description' excede 1024 caracteres")

        display_name = str(meta.get("display_name", name))
        argument_hint = meta.get("argument_hint")
        if argument_hint is not None:
            argument_hint = str(argument_hint)

        body = body_path.read_text(encoding="utf-8").strip()
        if not body:
            raise SyncError(f"{body_path}: corpo vazio")
        if body.startswith("---"):
            raise SyncError(f"{body_path}: FLOW.md deve conter apenas o corpo, sem frontmatter")

        flows.append(
            Flow(
                name=name,
                display_name=display_name,
                description=description,
                argument_hint=argument_hint,
                body=body,
            )
        )

    if not flows:
        raise SyncError(f"nenhum fluxo encontrado em {flows_dir}")

    skill_ids = {skill.name for skill in validate_skills(root)}
    overlap = skill_ids & seen
    if overlap:
        raise SyncError(f"flows e skills compartilham o mesmo ID: {sorted(overlap)}")
    return flows


# ---------------------------------------------------------------------------
# Renderização
# ---------------------------------------------------------------------------


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def model_for(agent: Agent, target: str) -> str | None:
    value = agent.models.get(target)
    if not value or value == "inherit":
        return None
    return value


def opencode_mode(modes: tuple[str, ...]) -> str:
    canonical = tuple(mode for mode in AGENT_MODES if mode in set(modes))
    try:
        return OPENCODE_MODES[canonical]
    except KeyError as exc:
        raise SyncError(f"modos inválidos para OpenCode: {list(modes)}") from exc


def opencode_permissions(tools: tuple[str, ...]) -> list[tuple[str, str]]:
    allowed = {OPENCODE_ACTIONS[tool] for tool in tools if tool in OPENCODE_ACTIONS}
    result: list[tuple[str, str]] = []
    for action in OPENCODE_ACTION_ORDER:
        if action not in allowed:
            result.append((action, "deny"))
    for action in OPENCODE_ACTION_ORDER:
        if action in allowed:
            result.append((action, "allow"))
    return result


def render_opencode_agent(agent: Agent) -> bytes:
    lines = [
        "---",
        f"description: {yaml_quote(agent.description)}",
        f"mode: {opencode_mode(agent.modes)}",
    ]
    if agent.color:
        lines.append(f"color: {yaml_quote(COLOR_HEX[agent.color])}")
    model = model_for(agent, "opencode")
    if model:
        lines.append(f"model: {yaml_quote(model)}")
    permissions = opencode_permissions(agent.tools)
    if permissions:
        lines.append("permissions:")
        for action, effect in permissions:
            lines.extend(
                [
                    f"  - action: {action}",
                    '    resource: "*"',
                    f"    effect: {effect}",
                ]
            )
    lines.extend(["---", "", GENERATED_COMMENT, "", agent.prompt, ""])
    return "\n".join(lines).encode("utf-8")


def render_claude_agent(agent: Agent) -> bytes:
    tools: list[str] = []
    for tool in agent.tools:
        mapped = CLAUDE_TOOLS.get(tool)
        if mapped and mapped not in tools:
            tools.append(mapped)
    if "TodoWrite" not in tools:
        tools.append("TodoWrite")

    lines = [
        "---",
        f"name: {agent.name}",
        f"description: {yaml_quote(agent.description)}",
        f"tools: {', '.join(tools)}",
    ]
    if agent.skills:
        lines.append("skills:")
        for skill in agent.skills:
            lines.append(f"  - {skill}")
    model = model_for(agent, "claude")
    if model:
        lines.append(f"model: {yaml_quote(model)}")
    if agent.color:
        lines.append(f"color: {agent.color}")
    lines.extend(["---", "", GENERATED_COMMENT, "", agent.prompt, ""])
    return "\n".join(lines).encode("utf-8")


def toml_escape_multiline(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = text.replace("\\", "\\\\")
    text = text.replace('"""', '\\"""')

    out: list[str] = []
    for char in text:
        if char in {"\n", "\t"}:
            out.append(char)
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return "".join(out)


def render_codex_agent(agent: Agent) -> bytes:
    lines = [
        f"# Gerado por scripts/sync_ai_assets.py a partir de ai/agents/{agent.name}/.",
        "# Não edite este arquivo.",
        f"# Ferramentas declaradas na fonte: {', '.join(agent.tools)}.",
        "# O Codex herda o sandbox da sessão.",
        "# Restrições de ferramenta por agente não são aplicadas.",
        f"name = {json.dumps(agent.name)}",
        f"description = {json.dumps(agent.description, ensure_ascii=False)}",
    ]
    model = model_for(agent, "codex")
    if model:
        lines.append(f"model = {json.dumps(model, ensure_ascii=False)}")
    if agent.reasoning_effort:
        lines.append(f"model_reasoning_effort = {json.dumps(agent.reasoning_effort)}")
    if "shell" not in agent.tools:
        lines.append("features.shell_tool = false")
    lines.extend(
        [
            'developer_instructions = """',
            toml_escape_multiline(agent.prompt),
            '"""',
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def render_codex_profile(agent: Agent) -> bytes:
    lines = [
        f"# Gerado por scripts/sync_ai_assets.py a partir de ai/agents/{agent.name}/.",
        "# Não edite este arquivo.",
        f"# Modo direto: instale como $CODEX_HOME/{agent.name}.config.toml e rode",
        f"# `codex --profile {agent.name}`.",
        "# O perfil adiciona developer_instructions à sessão; sandbox e aprovações",
        "# continuam vindo da sessão.",
    ]
    model = model_for(agent, "codex")
    if model:
        lines.append(f"model = {json.dumps(model, ensure_ascii=False)}")
    if agent.reasoning_effort:
        lines.append(f"model_reasoning_effort = {json.dumps(agent.reasoning_effort)}")
    if "shell" not in agent.tools:
        lines.append("features.shell_tool = false")
    lines.extend(
        [
            'developer_instructions = """',
            toml_escape_multiline(agent.prompt),
            '"""',
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def render_flow_skill(flow: Flow) -> bytes:
    lines = [
        "---",
        f"name: {flow.name}",
        f"description: {yaml_quote(flow.description)}",
        "disable-model-invocation: true",
    ]
    if flow.argument_hint:
        lines.append(f"argument-hint: {yaml_quote(flow.argument_hint)}")
    lines.extend(["---", "", GENERATED_COMMENT, "", flow.body, ""])
    return "\n".join(lines).encode("utf-8")


def render_opencode_command(flow: Flow) -> bytes:
    body = (
        f"Carregue a skill @{flow.name} e execute o fluxo para o pedido abaixo.\n\n"
        "Se o pedido estiver vazio, pergunte o objetivo e os critérios de aceite "
        "antes de começar.\n\n"
        "$ARGUMENTS\n"
    )
    lines = [
        "---",
        f"description: {yaml_quote(flow.description)}",
        "---",
        "",
        GENERATED_COMMENT,
        "",
        body,
    ]
    return "\n".join(lines).encode("utf-8")


def render_codex_flow_meta(flow: Flow) -> bytes:
    short = flow.description
    if len(short) > 120:
        short = short[:117].rstrip(" .") + "..."
    else:
        short = short.rstrip(".") + "." if short.endswith(".") else short
    lines = [
        f"# Gerado por scripts/sync_ai_assets.py a partir de ai/flows/{flow.name}/.",
        "# Não edite este arquivo.",
        "interface:",
        f"  display_name: {yaml_quote(flow.display_name)}",
        f"  short_description: {yaml_quote(short)}",
        "policy:",
        "  allow_implicit_invocation: false",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def skill_files(skill: Skill) -> list[tuple[Path, bytes, int]]:
    files: list[tuple[Path, bytes, int]] = []
    for path in sorted(skill.directory.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES or path.name in SKIP_NAMES:
            continue
        relpath = path.relative_to(skill.directory)
        data = path.read_bytes()
        if path.name == "SKILL.md":
            marker = (
                f"\n\n<!-- Gerado por scripts/sync_ai_assets.py. "
                f"Edite ai/skills/{skill.name}/SKILL.md. -->\n"
            )
            data = data.rstrip() + marker.encode("utf-8")
        mode = stat.S_IMODE(path.stat().st_mode)
        files.append((relpath, data, mode))
    return files


# ---------------------------------------------------------------------------
# Plano e escrita
# ---------------------------------------------------------------------------


def collect_plan(root: Path = ROOT) -> Plan:
    root = root.resolve()
    agents = load_agents(root)
    skills = validate_skills(root)
    flows = load_flows(root)

    instructions_path = root / "ai" / "instructions" / "AGENTS.md"
    if not instructions_path.is_file():
        raise SyncError(f"arquivo não encontrado: {instructions_path}")
    instructions = instructions_path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise SyncError(f"{instructions_path}: conteúdo vazio")

    plan = Plan()

    for agent in agents:
        plan.add(".opencode", f"agents/{agent.name}.md", render_opencode_agent(agent))
        plan.add(".claude", f"agents/{agent.name}.md", render_claude_agent(agent))
        if "subagent" in agent.modes:
            plan.add(".codex", f"agents/{agent.name}.toml", render_codex_agent(agent))
        if "direct" in agent.modes:
            plan.add(
                ".codex",
                f"profiles/{agent.name}.config.toml",
                render_codex_profile(agent),
            )

    for skill in skills:
        for target in (".opencode", ".claude", ".agents"):
            for relpath, data, mode in skill_files(skill):
                plan.add(target, f"skills/{skill.name}/{relpath.as_posix()}", data, mode)

    for flow in flows:
        for target in (".opencode", ".claude", ".agents"):
            plan.add(target, f"skills/{flow.name}/SKILL.md", render_flow_skill(flow))
        plan.add(".agents", f"skills/{flow.name}/agents/openai.yaml", render_codex_flow_meta(flow))
        plan.add(".opencode", f"commands/{flow.name}.md", render_opencode_command(flow))

    root_doc = (GENERATED_COMMENT + "\n\n" + instructions + "\n").encode("utf-8")
    plan.files["AGENTS.md"] = (root_doc, 0o644)
    plan.files["CLAUDE.md"] = (root_doc, 0o644)

    for target in TARGETS:
        manifest = {
            "generator": "scripts/sync_ai_assets.py",
            "source": "ai/",
            "files": sorted(plan.managed[target]),
        }
        data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        plan.files[f"{target}/{MANIFEST_NAME}"] = (data, 0o644)

    return plan


def read_manifest(target_dir: Path) -> set[str]:
    path = target_dir / MANIFEST_NAME
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    files = data.get("files", [])
    if not isinstance(files, list):
        return set()
    return {str(item) for item in files}


def remove_empty_parents(path: Path, stop: Path) -> None:
    parent = path.parent
    while parent != stop and parent.is_dir():
        try:
            next(parent.iterdir())
        except StopIteration:
            parent.rmdir()
            parent = parent.parent
        else:
            break


def write_plan(plan: Plan, root: Path = ROOT) -> None:
    root = root.resolve()

    for target in TARGETS:
        target_dir = root / target
        old = read_manifest(target_dir)
        new = set(plan.managed.get(target, []))
        for relpath in sorted(old - new):
            path = target_dir / relpath
            if path.is_file() or path.is_symlink():
                path.unlink()
                remove_empty_parents(path, target_dir)

    for relpath in sorted(plan.files):
        data, mode = plan.files[relpath]
        path = root / relpath
        if path.is_dir():
            raise SyncError(f"caminho de arquivo é um diretório: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if os.name != "nt":
            path.chmod(mode)


def check_plan(plan: Plan, root: Path = ROOT) -> list[str]:
    root = root.resolve()
    issues: list[str] = []

    for relpath in sorted(plan.files):
        data, mode = plan.files[relpath]
        path = root / relpath
        if not path.is_file():
            issues.append(f"faltando: {relpath}")
            continue
        if path.read_bytes() != data:
            issues.append(f"desatualizado: {relpath}")
            continue
        if os.name != "nt":
            actual = stat.S_IMODE(path.stat().st_mode)
            if actual != mode:
                issues.append(f"modo diferente: {relpath} ({oct(actual)} != {oct(mode)})")

    for target in TARGETS:
        target_dir = root / target
        old = read_manifest(target_dir)
        new = set(plan.managed.get(target, []))
        for relpath in sorted(old - new):
            if (target_dir / relpath).exists():
                issues.append(f"obsoleto: {target}/{relpath}")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza ai/ com OpenCode, Claude Code e Codex."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="não escreve; falha se os arquivos gerados estiverem dessincronizados",
    )
    args = parser.parse_args(argv)

    try:
        plan = collect_plan()
    except SyncError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    if args.check:
        issues = check_plan(plan)
        if issues:
            print("Assets de IA dessincronizados:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            print("\nRode: python scripts/sync_ai_assets.py", file=sys.stderr)
            return 1
        print("Assets de IA sincronizados.")
        return 0

    write_plan(plan)
    print(
        "Sincronizados "
        f"{len(plan.files)} arquivos em .opencode/, .claude/, .agents/, .codex/ e raiz."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
