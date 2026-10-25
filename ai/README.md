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
├── prompts/             # prompts de implementação (não espelhados)
└── instructions/
    └── AGENTS.md        # instruções compartilhadas
```

## Agentes

### `agent.json`

| Campo | Obrigatório | Descrição |
| --- | --- | --- |
| `name` | sim | ID em kebab-case; deve ser igual ao diretório. |
| `description` | sim | Quando usar o agente; até 1024 caracteres. |
| `modes` | sim | Lista não vazia com `direct`, `subagent` ou ambos. |
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

### Modos de uso

Cada agente declara em `modes` onde pode ser usado:

| Modo | OpenCode | Claude Code | Codex |
| --- | --- | --- | --- |
| `direct` | agente principal (`Tab` ou `default_agent`) | `claude --agent <id>` ou setting `agent` | `codex --profile <id>` |
| `subagent` | `@<id>` ou delegação automática | tool Agent ou “use o agente `<id>`” | `.codex/agents/<id>.toml` |
| ambos | `mode: all` | o mesmo arquivo atende aos dois contextos | agente + perfil |

O OpenCode recebe `mode: primary`, `subagent` ou `all` conforme os modos declarados. O Claude Code usa o mesmo `.claude/agents/<id>.md` nos dois contextos; ele não tem campo para restringir o modo. No Codex, o modo direto é um perfil em `.codex/profiles/<id>.config.toml`, porque o Codex lê perfis apenas de `$CODEX_HOME`.

Para ativar o perfil do Codex no Linux ou macOS:

```bash
mkdir -p "$HOME/.codex"
ln -sfn "$PWD/.codex/profiles/<id>.config.toml" "$HOME/.codex/<id>.config.toml"
codex --profile <id>
```

Reversão: `rm "$HOME/.codex/<id>.config.toml"`. No Windows, copie o arquivo para `%USERPROFILE%\.codex\<id>.config.toml` e repita a cópia depois de cada sync. O perfil adiciona `developer_instructions`, modelo e esforço; sandbox, aprovações e autenticação continuam vindo da sessão.

### `prompt.md`

Corpo do system prompt, em PT-BR, com:

1. Papel
2. Missão
3. Escopo
4. Modos de execução
5. Princípios/processo
6. Regras
7. Contrato de saída
8. Handoffs
9. Limites

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

## Prompts de implementação

Prompts de trabalho ficam em `ai/prompts/`. Eles não são skills nem agentes e não são espelhados pelo gerador.

- Use um prompt por incremento verificável.
- O prompt define objetivo, escopo, fora de escopo, critérios de aceite e validação.
- No Claude Code, referencie `@ai/prompts/<arquivo>.md`; no Codex, referencie `ai/prompts/<arquivo>.md` ou cole o conteúdo.
- O prompt não substitui as skills; `evidence-based`, `clean-code`, `clean-architecture` e `python-quality` continuam valendo.

O primeiro prompt é `01-runtime-cli-end-to-end.md`, para o comando `zonepad run` com evdev → perfil → uinput.

## Instruções compartilhadas

`ai/instructions/AGENTS.md` é copiado para `AGENTS.md` e `CLAUDE.md`. Mantenha-o curto: ele entra em toda sessão. Regras detalhadas vão para skills.

## Sincronização

```bash
python scripts/sync_ai_assets.py           # escreve
python scripts/sync_ai_assets.py --check   # compara e falha se houver drift
```

O gerador:

- valida nomes, descrições, modos, ferramentas, skills e fluxos;
- converte agentes para Markdown/YAML e TOML e gera perfis Codex para o modo direto;
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
