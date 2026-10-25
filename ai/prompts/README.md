# Prompts de implementação

Esta pasta guarda prompts de trabalho para implementar o ZonaPad com Claude Code ou Codex. Eles **não** são skills nem agentes: são entradas versionadas para uma sessão de implementação.

Os prompts não são espelhados pelo gerador `scripts/sync_ai_assets.py`. Eles vivem apenas em `ai/prompts/` e podem ser referenciados por caminho.

## Como usar

### Claude Code

```text
Use o prompt em @ai/prompts/03-calibration-wizard.md.
Leia o arquivo inteiro, execute as etapas na ordem e valide com os comandos pedidos.
```

Ou use o fluxo:

```text
/flow-implement-feature
```

Para o prompt 03, comece por `/flow-design-feature` antes de `/flow-implement-feature`.

### Codex

```text
Siga o prompt em ai/prompts/03-calibration-wizard.md.
Leia o arquivo inteiro, execute as etapas na ordem e valide com os comandos pedidos.
```

Ou use a skill de fluxo:

```text
$flow-implement-feature
```

Para o prompt 03, comece por `$flow-design-feature` antes de `$flow-implement-feature`.

## Convenções

- Um prompt por incremento verificável.
- O prompt define objetivo, escopo, fora de escopo, critérios de aceite e validação.
- O agente deve ler `AGENTS.md`, o ADR relevante e os arquivos citados antes de editar.
- O prompt não substitui as skills: `evidence-based`, `clean-code`, `clean-architecture` e `python-quality` continuam valendo.
- Se o incremento mudar contrato público, o agente deve propor um ADR.
- Se o incremento mexer em `ai/`, rodar `python scripts/sync_ai_assets.py` e `--check`.

## Sequência planejada

Os prompts 00, 01 e 02 estão concluídos e mergeados em `main`. O prompt 03 está implementado e aguardando merge. Execute cada incremento em branch própria criada a partir de `main`, com worktree limpo e toolchain 3.15.0.

| Prompt | Incremento | Status |
| --- | --- | --- |
| `00-toolchain-python-315-asdf-virtualenv.md` | Python 3.15.0, asdf, virtualenv, pyproject e CI | Concluído — mergeado em `main` |
| `01-runtime-cli-end-to-end.md` | Comando `zonepad run` com evdev → perfil → uinput | Concluído — mergeado em `main` |
| `02-calibration-metrics.md` | Métricas, relatório e profile builder | Concluído — mergeado no PR #5 (spec `docs/specs/metrics-v1.md`, ADR `docs/adr/0004-metricas-relatorio-separado-e-perfil-v1.md`) |
| `03-calibration-wizard.md` | Wizard CLI de calibração | Implementado — aguardando merge |
| `04-device-discovery-mapping.md` | Descoberta e mapeamento por família | A criar |
| `05-gui-pyside6.md` | GUI funcional | A criar |
| `06-quality-release.md` | Ruff/mypy/cobertura/packaging | A criar |

O prompt 02 é pré-requisito do 03: ele entrega o motor de medição e a geração de perfil; o wizard apenas orquestra esse motor e a política de retry. O prompt 04 substitui a seleção manual de dispositivo e o mapping manual usados no 03.

## Regra de ouro

Se o agente não conseguir validar sem hardware, ele deve:

1. criar um teste com fake/replay;
2. documentar o smoke manual necessário;
3. declarar explicitamente o que não foi validado.
