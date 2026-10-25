# ADR 0005 — Wizard interativo `zonepad calibrate`

- **Status:** aceito
- **Data:** 2026-10-25
- **Spec:** [`docs/specs/wizard-v1.md`](../specs/wizard-v1.md)

## Contexto

`zonepad measure` aceita captura JSONL, manifesto e mapping, mas não produz uma sessão guiada. A pessoa precisa seguir o protocolo, revisar a qualidade e decidir se quer persistir o perfil. O wizard deve reaproveitar as métricas e a derivação existentes, mantendo o perfil v1 inalterado.

## Decisão

1. `calibrate` é um subcomando aditivo da CLI e exige TTY para execução. A seleção manual usa `DeviceBackend`; a validação de mapping e thresholds acontece antes de abrir o dispositivo.
2. A coordenação de aplicação usa estados/eventos imutáveis e um reducer puro. Console, relógio, sessão de captura, runner e armazenamento entram por portas.
3. A captura raw é JSONL estrito com timestamps monotônicos rebaseados para zero. Um manifesto v1 declara janelas semiabertas; retries substituem a janela lógica do alvo e deixam frames antigos fora das métricas.
4. `MeasureRunner` chama `read_strict_capture`, `load_manifest` e `execute_measure` com `strict=True` e `save_profile=True`. O wizard exibe o resultado existente e não recalcula qualidade.
5. Relatórios JSON/Markdown são gravados antes do perfil. `JsonProfileStore` recebe somente um `MeasureOutcome` com perfil derivado, mantendo `schema_version=1`.
6. As tentativas são limitadas por alvo e globalmente. Só códigos e métricas explicitamente elegíveis iniciam retry; resultado bloqueante sem alvo seguro retorna 4.
7. Diretórios locais contêm `capture.jsonl`, `capture.manifest.json`, `report.json` e `report.md`. Nomes usam timestamp UTC civil, identificador do nó sanitizado e sufixo numérico em colisões.
8. O backend evdev atual não expõe VID/PID; `0x0000` representa somente o valor desconhecido. Esse campo não identifica uma família de controle.
9. Cancelamento e desconexão fecham a sessão e preservam a captura parcial sem manifesto, relatório ou perfil.

## Consequências

- Capturas podem ser reavaliadas por `zonepad measure` e os perfis continuam carregáveis por `zonepad run`.
- Evdev emite frames em `SYN_REPORT`; um controle parado pode não fornecer os frames mínimos do repouso. A qualidade resultante permanece decisão do motor.
- A sessão captura continuamente em uma thread enquanto o terminal aguarda confirmações. Relógio e sessão fake mantêm os testes sem hardware e sem espera real.
- A seleção continua manual e o mapping continua fornecido pela pessoa; descoberta e mapping automático pertencem ao incremento seguinte.

## Alternativas consideradas

- Implementar métricas no wizard: rejeitada para preservar `metrics-v1` como fonte única de qualidade.
- Persistir o perfil antes do relatório: rejeitada para não deixar perfil sem artefatos explicativos.
- Inferir VID/PID ou mapping: rejeitada; backend e protocolo atual não têm informação suficiente.
- Capturar apenas durante janelas declaradas: rejeitada; frames de instrução e pausas ajudam a preservar a linha temporal, mas não participam das métricas.
