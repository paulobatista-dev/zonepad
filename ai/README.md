# Assets de IA — guia de autoria

Esta pasta é a **fonte canônica** dos agentes, skills, fluxos e instruções compartilhadas. Os diretórios das ferramentas são gerados por `scripts/sync_ai_assets.py`.

## Layout

```text
ai/
├── agents/<id>/
│   ├── agent.json       # metadados portáveis
│   └── prompt.md        # system prompt (corpo)
├── skills/<id>/
│   ├── SKILL.md         # frontmatter + instruções
│   └── references/      # material carregado sob demanda
├── flows/<id>/
│   ├── flow.json        # metadados do fluxo
│   └── FLOW.md          # corpo, sem frontmatter
└── instructions/
    └── AGENTS.md        # instruções compartilhadas
```

## Agentes

### `agent.json`

| Campo | Obrigatório | Descrição |
| --- | --- | --- |
| `name` | sim | ID em kebab-case; deve ser igual ao diretório. |
| `description` | sim | Quando usar o agente; até 1024 caracteres. |
| `mode` | não | `subagent` (padrão), `primary` ou `all`. |
| `tools` | sim | Lista de ferramentas canônicas. |
| `skills` | não | Skills que o agente deve usar. |
| `color` | não | `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink` ou `cyan`. |
| `models` | não | Override por alvo: `opencode`, `claude`, `codex`; `null` = herdar. |
| `reasoning_effort` | não | Apenas Codex: `low`, `medium`, `high`, `xhigh`, `max` ou `ultra`. |

Ferramentas canônicas:

`read`, `write`, `edit`, `glob`, `grep`, `shell`, `webfetch`, `websearch`, `skill`, `subagent`.

Mapeamento:

| Canônica | OpenCode | Claude Code | Codex |
| --- | --- | --- | --- |
| `read` | `read` | `Read` | herdado |
| `write` | `edit` | `Write` | herdado |
| `edit` | `edit` | `Edit` | herdado |
| `glob` | `glob` | `Glob` | herdado |
| `grep` | `grep` | `Grep` | herdado |
| `shell` | `shell` | `Bash` | `features.shell_tool` |
| `webfetch` | `webfetch` | `WebFetch` | herdado |
| `websearch` | `websearch` | `WebSearch` | herdado |
| `skill` | `skill` | `Skill` | herdado |
| `subagent` | `subagent` | `Agent` | herdado |

O Codex não tem restrição de ferramenta por agente; o gerador só desabilita `features.shell_tool` quando `shell` não está na lista.

### `prompt.md`

Corpo do system prompt, em PT-BR, com:

1. Papel
2. Missão
3. Escopo
4. Princípios/processo
5. Regras
6. Contrato de saída
7. Handoffs
8. Limites

Não coloque frontmatter em `prompt.md`.

## Skills

`SKILL.md` segue o padrão Agent Skills:

```yaml
---
name: minha-skill
description: O que faz e quando usar. Inclua gatilhos e fronteiras.
metadata:
  owner: python-engineer
  version: "1.0"
---
```

Regras:

- `name` deve ser igual ao diretório, em kebab-case.
- `description` deve ser uma única linha, com até 1024 caracteres.
- O corpo deve ficar abaixo de ~500 linhas; detalhes vão para `references/`.
- Use caminhos relativos ao diretório da skill.
- Não use campos específicos de uma ferramenta no frontmatter canônico.
- Skills de fluxo são geradas a partir de `ai/flows/`, não ficam em `ai/skills/`.

## Fluxos

### `flow.json`

| Campo | Obrigatório | Descrição |
| --- | --- | --- |
| `name` | sim | `flow-<id>` em kebab-case; igual ao diretório. |
| `description` | sim | Quando usar o fluxo; até 1024 caracteres. |
| `display_name` | não | Nome exibido no Codex. |
| `argument_hint` | não | Dica de argumentos para Claude/OpenCode. |

### `FLOW.md`

Corpo do fluxo, sem frontmatter. Use as seções:

- Quando usar
- Entradas
- Passos
- Como delegar
- Saída esperada
- Critérios de pronto

O gerador cria a skill com:

```yaml
name: flow-...
description: ...
disable-model-invocation: true
argument-hint: ...
```

Isso torna o fluxo explícito em OpenCode e Claude. No Codex, o `agents/openai.yaml` gerado também define `allow_implicit_invocation: false`.

## Instruções compartilhadas

`ai/instructions/AGENTS.md` é copiado para `AGENTS.md` e `CLAUDE.md`. Mantenha-o curto: ele entra em toda sessão. Regras detalhadas vão para skills.

## Sincronização

```bash
python scripts/sync_ai_assets.py           # escreve
python scripts/sync_ai_assets.py --check   # compara e falha se houver drift
```

O gerador:

- valida nomes, descrições, ferramentas, skills e fluxos;
- converte agentes para Markdown/YAML e TOML;
- copia skills e gera fluxos;
- grava um manifesto `.generated.json` por destino;
- remove arquivos obsoletos listados no manifesto;
- não remove arquivos que você criou manualmente fora do manifesto.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes cobrem idempotência, TOML válido, espelhamento, permissões do OpenCode, round-trip de escrita/check e detecção de drift.

## Convenções

- Conteúdo em PT-BR; identificadores em inglês.
- Uma responsabilidade por skill.
- Sem duplicação entre agente, skill, fluxo e `AGENTS.md`.
- Segurança é regra, não preferência.
- Toda mudança de comportamento deve poder ser avaliada por `prompt-evaluation`.
