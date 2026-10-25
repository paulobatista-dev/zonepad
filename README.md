# ZonaPad

Aplicativo Python para calibrar controles (gamepads) de forma guiada e reproduzível. O MVP atual é Linux-only; portas mantêm o domínio portátil para backends futuros.

> **Estado atual:** MVP Linux com pipeline raw → normalizado → calibrado, replay determinístico, perfis JSON versionados, CLI e GUI Qt opcional.

## Instalação e uso

```bash
python -m pip install -e .
zonepad list
zonepad profiles --directory ~/.config/zonepad/profiles
zonepad replay captura.jsonl
```

O backend Linux lê `/dev/input/event*` (evdev), aplica o perfil em tempo real e publica eventos em um controle virtual por `/dev/uinput`. O acesso ao dispositivo `uinput` depende das permissões da distribuição. Nenhum acesso a hardware é executado nos testes.

O runtime programático é exposto por `zonepad.application.runtime.run_saved_profile`; a CLI inicial cobre descoberta, perfis e replay. A composição de ranges medidos por controle e o wizard completo de calibração são os próximos incrementos da interface.

Para a GUI, instale o extra opcional: `python -m pip install -e '.[gui]'` e execute `zonepad-gui`.

## Arquitetura

`zonepad.domain` contém frames imutáveis, normalização, transformações e perfil validado. `zonepad.application` define portas e orquestra leitura. `zonepad.infrastructure` implementa evdev, uinput, replay, fakes e persistência JSON. `zonepad.interface` fornece CLI e GUI opcional.

Perfis são salvos atomicamente em JSON com `schema_version=1`; campos desconhecidos, ranges inválidos, UUIDs não-v4 e números não finitos são rejeitados.

## O que existe

- **3 agentes especialistas** com escopo, processo, contrato de saída e handoffs.
- **12 skills** com procedimentos e referências progressivas.
- **4 fluxos** multiagente para bootstrap, design, implementação e revisão.
- **Fonte canônica única** em `ai/`, espelhada para OpenCode, Claude Code e Codex.
- **Gerador idempotente** com validação `--check` para CI.

## Estrutura

```text
.
├── ai/                          # fonte canônica (edite aqui)
│   ├── agents/<id>/             # agent.json + prompt.md
│   ├── skills/<id>/             # SKILL.md + references/scripts/assets
│   ├── flows/<id>/              # flow.json + FLOW.md
│   ├── prompts/                 # prompts de implementação
│   └── instructions/AGENTS.md
├── scripts/
│   └── sync_ai_assets.py        # gera os espelhos
├── tests/
│   └── test_sync_ai_assets.py
├── .opencode/                   # gerado: agentes, skills, comandos
├── .claude/                     # gerado: agentes, skills
├── .agents/                     # gerado: skills (Codex)
├── .codex/                      # gerado: agentes TOML
├── AGENTS.md                    # gerado: OpenCode/Codex
├── CLAUDE.md                    # gerado: Claude Code
├── LICENSE                      # licença MIT
└── README.md                    # visão geral, uso e arquitetura
```

## Fonte canônica

Nunca edite `.opencode/`, `.claude/`, `.agents/`, `.codex/`, `AGENTS.md` ou `CLAUDE.md`. Eles são gerados e sobrescritos.

Fluxo de trabalho:

```bash
# 1. edite ai/
# 2. gere os espelhos
python scripts/sync_ai_assets.py

# 3. valide antes de concluir
python scripts/sync_ai_assets.py --check
python -m pytest
```

## Agentes

| Agente | Especialidade | Skills principais |
| --- | --- | --- |
| `prompt-engineer` | Prompts, skills, fluxos, avaliação e custo de contexto. | `prompt-design`, `prompt-evaluation`, `positive-ontology`, `evidence-based`, `github-interaction` |
| `python-engineer` | Arquitetura, código, testes, tipagem e packaging. | `python-app-architecture`, `python-quality`, `clean-code`, `clean-architecture`, `calibration-domain`, `evidence-based`, `github-interaction` |
| `controller-hardware` | HID/SDL3, protocolos, medição e calibração. | `controller-protocols`, `calibration-metrics`, `calibration-domain`, `positive-ontology`, `evidence-based` |

Como acionar:

- **OpenCode:** peça ao agente principal para usar o subagente (`prompt-engineer`, `python-engineer` ou `controller-hardware`).
- **Claude Code:** peça "use o subagente `python-engineer`" ou confie na delegação automática pela descrição.
- **Codex:** peça "use o agente `controller-hardware`" ou solicite subagentes em paralelo.

## Skills

| Skill | Dono | Quando usar |
| --- | --- | --- |
| `prompt-design` | prompt-engineer | Criar/revisar agente, skill ou fluxo. |
| `positive-ontology` | prompt-engineer / hardware | Definir comportamentos e critérios de forma afirmativa e observável. |
| `prompt-evaluation` | prompt-engineer | Testar disparo, regressão e qualidade de prompt. |
| `evidence-based` | compartilhada | Separar fato, inferência, suposição e recomendação; exigir evidência. |
| `python-app-architecture` | python-engineer | Decidir camadas, portas e fluxo de dados no ZonaPad. |
| `clean-code` | python-engineer | Nomes, funções, erros, testes e legibilidade do código. |
| `clean-architecture` | python-engineer | Regra de dependência, boundaries, portas e adaptadores. |
| `python-quality` | python-engineer | Testes, lint, tipos, CI e performance. |
| `controller-protocols` | controller-hardware | Integrar dispositivo e interpretar relatórios. |
| `calibration-metrics` | controller-hardware | Medir e definir critérios de calibração. |
| `calibration-domain` | compartilhada | Modelo de frames, pipeline e schema de perfil. |
| `github-interaction` | compartilhada | Inspecionar repo, issues, PRs, checks, releases e Actions com segurança. |

Invocação:

- **OpenCode:** `@prompt-design` ou carregamento automático pela descrição.
- **Claude Code:** `/prompt-design` ou carregamento automático.
- **Codex:** `$prompt-design` ou carregamento automático.

## Fluxos

| Fluxo | Objetivo |
| --- | --- |
| `flow-bootstrap-app` | Criar MVP, arquitetura, contratos, esqueleto, README e licença. |
| `flow-design-feature` | Especificar uma feature antes de codar. |
| `flow-implement-feature` | Implementar uma spec aprovada com testes e revisão. |
| `flow-review-calibration` | Revisão multiagente de código e medições. |

Invocação:

- **OpenCode:** `/flow-bootstrap-app` ou `@flow-bootstrap-app`.
- **Claude Code:** `/flow-bootstrap-app`.
- **Codex:** `$flow-bootstrap-app`.

## Prompts de implementação

Prompts versionados em `ai/prompts/` para executar incrementos no Claude Code ou Codex. Eles não são espelhados pelo gerador.

- **Claude Code:** referencie `@ai/prompts/01-runtime-cli-end-to-end.md`.
- **Codex:** referencie `ai/prompts/01-runtime-cli-end-to-end.md` ou cole o conteúdo.
- O primeiro incremento é o comando `zonepad run` com evdev → perfil → uinput.

## GitHub

A skill `github-interaction` cobre diagnóstico, issues, branches, commits, pull requests, checks, revisões, releases e GitHub Actions.

Pré-requisito: `gh auth status` deve indicar autenticação. Se o GitHub CLI não estiver instalado, instale `gh` e rode `gh auth login` em um terminal interativo. Operações de escrita exigem intenção explícita; merge e ações destrutivas são confirmados antes de executar.

## Como funciona o espelhamento

| Conceito | OpenCode | Claude Code | Codex |
| --- | --- | --- | --- |
| Instruções | `AGENTS.md` | `CLAUDE.md` | `AGENTS.md` |
| Skills | `.opencode/skills/` | `.claude/skills/` | `.agents/skills/` |
| Agentes | `.opencode/agents/*.md` | `.claude/agents/*.md` | `.codex/agents/*.toml` |
| Fluxos | `.opencode/skills/` + `.opencode/commands/` | `.claude/skills/` | `.agents/skills/` |

O gerador:

1. Lê os metadados JSON e os corpos Markdown de `ai/`.
2. Converte os agentes para os três schemas (Markdown/YAML e TOML).
3. Copia skills canônicas e gera as skills de fluxo.
4. Gera comandos `/flow-...` para OpenCode.
5. Gera `agents/openai.yaml` para desabilitar invocação implícita dos fluxos no Codex.
6. Mantém um manifesto `.generated.json` em cada destino e remove arquivos obsoletos.
7. Compara tudo em `--check` sem escrever.

> **Escopo:** os espelhos são do projeto. Para uso global, copie os diretórios gerados para `~/.config/opencode/`, `~/.claude/` e `~/.agents/`/`~/.codex/`, conforme a ferramenta.

## Adicionar um agente

1. Crie `ai/agents/<id>/agent.json` e `prompt.md`.
2. Use as chaves `name`, `description`, `tools`, `skills`, `models`, `reasoning_effort` e `color`.
3. Rode o gerador e confira os três espelhos.
4. Adicione casos de avaliação em `ai/skills/prompt-evaluation/references/test-matrix.md`.

## Adicionar uma skill

1. Crie `ai/skills/<id>/SKILL.md` com frontmatter `name` e `description`.
2. Mantenha o nome igual ao diretório, em kebab-case.
3. Mova conteúdo extenso para `references/`.
4. Declare a skill em `skills` do agente que deve usá-la.

## Adicionar um fluxo

1. Crie `ai/flows/flow-<id>/flow.json` e `FLOW.md`.
2. `FLOW.md` contém apenas o corpo, sem frontmatter.
3. O fluxo é gerado como skill com `disable-model-invocation: true`.
4. No Codex, invoque com `$flow-<id>`; nos demais, `/flow-<id>`.

## Compatibilidade e limites

- Skills seguem o padrão [Agent Skills](https://agentskills.io/specification), mas cada ferramenta tem extensões próprias.
- Agentes **não** são portáveis byte a byte: OpenCode usa `permissions`, Claude usa `tools`/`skills` e Codex usa TOML. O gerador traduz o subconjunto comum.
- O Codex não aplica restrições de ferramenta por agente além de feature toggles; as regras de escopo são comportamentais.
- Prompts customizados do Codex estão deprecated e são globais; por isso os fluxos são skills explícitas.
- O Claude pré-carrega as skills listadas em `skills` no subagente; isso consome contexto.
- O OpenCode não cria slash commands a partir de skills; os comandos de fluxo são gerados separadamente.
- Skills são copiadas para três diretórios. Edite sempre `ai/`.

## Validação

```bash
python -m unittest discover -s tests -v
python scripts/sync_ai_assets.py --check
```

A CI em `.github/workflows/ai-assets.yml` roda os dois comandos.

## Licença

Distribuído sob a licença MIT. Veja [LICENSE](LICENSE).

Copyright (c) 2026 ZonaPad contributors.

## Próximos passos

1. Completar o registro/mapeamento de dispositivos uinput por família de controle.
2. Adicionar métricas guiadas de ruído, circularidade, linearidade e histerese.
3. Implementar descoberta hot-plug e parsers específicos após capturas reais.
