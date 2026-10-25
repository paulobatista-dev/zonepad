# ADR 0008 — GUI PySide6 como adaptador

- **Status:** aceito pelo usuário em 2026-10-25.
- **Data:** 2026-10-25.
- **Spec:** [`docs/specs/gui-v1.md`](../specs/gui-v1.md).

## Contexto

O MVP já fornece frames raw, normalização, perfis validados, descoberta por identidade estável, store de mappings, state machine do wizard, captura, motor de métricas e `ProfileStore`. A interface gráfica atual é um placeholder. A GUI precisa reunir essas capacidades mantendo as regras de domínio nas camadas existentes e o binding Qt opcional.

`NormalizedFrame` representa sticks em `[-1,1]` e triggers em `[0,1]`. `RawFrame` guarda valores inteiros de evdev em counts. `CalibratedFrame` preserva as faixas normalizadas após `apply_profile`. `Finding` contém código, severidade, mensagem, caminho de métrica, valor e threshold. Esses contratos definem o que a tela pode apresentar.

O reducer `application.calibrate.step` controla fases e efeitos, enquanto seleção de dispositivo, mapping, outcomes, artifacts e contadores detalhados pertencem ao coordenador da borda. O CLI concentra parte da apresentação e de alguns helpers privados, incluindo planos/instruções e resolução de retry. A GUI requer contratos compartilhados para manter paridade.

## Decisão

1. **Binding opcional.** Manter o extra `gui` com `PySide6>=6.7` como binding Qt do projeto. O entry point é `zonepad-gui = zonepad.interface.gui:run`. O módulo público valida `--help`, `--version` e `--smoke` antes de importar Qt; a ausência de PySide6 retorna exit 2 e informa o comando de instalação. A versão usada no ambiente de design é PySide6 6.12.0.
2. **Composição.** `gui/app.py` cria uma única `QApplication` e compõe uma `QMainWindow`. A janela contém navegação e `QStackedWidget` para Dispositivos, Monitor, Calibração e Perfis. Somente a composição cria `QApplication`.
3. **Fronteira de apresentação.** View-models são Python puro com estados imutáveis, comandos e formatação. Adapters coordenam aplicação, infraestrutura e sinais Qt. Widgets apresentam snapshots e emitem ações; composição injeta dependências explicitamente.
4. **Desenho.** Usar `QPainter` para planos de stick, barras de trigger, indicadores de botão e medidores. O projeto mantém dependências gráficas enxutas e cada widget controla sua escala e legenda.
5. **Camadas e unidades.** Um caso de uso de aplicação transforma `RawFrame` em `NormalizedFrame` por `normalize_frame` e entrega snapshots imutáveis ao monitor. A GUI apresenta sticks `[-1,1]`, triggers `[0,1]` e os estados do subconjunto de botões espaciais presentes no mapping v1; botão pressionado aparece quando seu nome está no frame, e os demais botões mapeados aparecem soltos. Mapping sem botões mostra o estado “Nenhum botão mapeado”. Camada, faixas e estados textuais ficam visíveis. A coordenada y do desenho usa positivo para cima e o valor textual preserva o sinal do frame. Raw permanece em counts nos fluxos de captura/diagnóstico; `CalibratedFrame` fica para uma versão que ofereça aplicação explícita de perfil.
6. **Descoberta e perfis.** A GUI chama `discover_devices`, `resolve_device_reference`, `resolve_mapping` e `PollingHotplugWatcher` atuais. A seleção persiste por `StableIdentity`; `eventN` serve como detalhe diagnóstico. Mapping ausente/inválido mantém estado visível e oferece `zonepad mapping draft --device <id>`; Monitor e Calibração exigem mapping válido para abrir/interpretar a sessão. Identidade frágil apresenta confirmação antes da calibração. Uma porta de aplicação enumera perfis via adapter `JsonProfileStore`; cada perfil é carregado individualmente e uma falha mantém os demais disponíveis. Diagnósticos mostram caminho relativo à pasta configurada.
7. **Workflow do wizard.** Reutilizar `WizardPhase`, `step`, findings e `ProfileStore`. Uma porta de medição da aplicação liga o workflow ao `MeasureRunner` na composição. Um contexto imutável do workflow mantém seleção, mapping, resultado, artifacts e contadores na borda; reducer recebe eventos de aplicação e continua livre de Qt e I/O.
8. **Contratos compartilhados.** Extrair planos, instruções, conversão para `Segment` e resolução dos alvos de retry de `interface/calibration_cli.py` para `application/`. O CLI e a GUI passam a consumir a mesma fonte. Defaults, mensagens, política de retry, achados e critérios permanecem iguais ao wizard v1.
9. **Concorrência.** Um worker possui a leitura da sessão e comunica snapshots imutáveis por sinais Qt. Monitor limita repintura a 30 Hz e mantém o snapshot mais recente. A taxa observada de frames usa `Hz = (n - 1) / (t_último - t_primeiro)` sobre timestamps distintos na janela móvel mais recente de 1 s, com dois frames como mínimo. Captura persiste todos os frames; a taxa de apresentação preserva a aquisição integral. O lifecycle coordena a thread existente de `LiveCaptureSession` sob um único dono da sessão. `QTimer` faz polling de hot-plug.
10. **Encerramento.** Fechamento para timers, solicita cancelamento cooperativo, fecha a sessão e aguarda a thread até 2 s. Leituras usam timeout para responder ao cancelamento; uma falha de shutdown é registrada em log estruturado.
11. **Testes e acessibilidade.** Testes Qt usam `QT_QPA_PLATFORM=offscreen`, uma fixture `QApplication` e `QSignalSpy`. View-models usam pytest puro. A experiência apresenta textos PT-BR, ordem de tabulação, accessible names, fontes escaláveis, atalhos Ctrl+R/Esc e estado textual além de cor.
12. **Limite v1.** A aplicação suporta Linux e um dispositivo por vez. Monitor é somente leitura e normalizado; painel de perfis oferece inspeção, e wizard cria perfil. Aplicação de perfil ao runtime, edição/exclusão e criação de mapping draft permanecem para incrementos futuros.

## Consequências

- A CLI e a GUI compartilham instruções e política de retry; paridade pode ser verificada com testes determinísticos.
- View-models permanecem executáveis sem Qt e facilitam teste de estado sem inicializar aplicação gráfica.
- O binding segue opcional e os comandos de terminal mantêm importabilidade em instalações sem extra GUI.
- O monitor descreve valores device-independent e deixa clara sua camada; contagens raw permanecem associadas a diagnóstico/captura.
- O uso de worker e snapshots preserva responsividade; captura íntegra segue separada da frequência visual.
- Perfis danificados têm estado local por item e os demais permanecem inspecionáveis.
- Layouts e foco variam entre ambientes gráficos; `offscreen` cobre contratos e revisão visual manual futura cobre apresentação em desktop.

## Alternativas consideradas

- **Aplicar perfil no monitor v1.** Adicionaria uma segunda camada visual e exigiria seleção/associação de perfil ao dispositivo. A versão inicial mostra a camada normalizada e mantém o painel Perfis como inspeção; aplicação ao runtime fica em incremento posterior.
- **Usar Qt Charts, Matplotlib ou pyqtgraph.** Widgets com `QPainter` entregam as formas necessárias, controlam unidades diretamente e mantêm uma única dependência de GUI.
- **Usar `run_calibrate` da CLI na GUI.** Esse orquestrador depende de TTY e helpers de interface. O coordenador GUI executa o reducer e portas diretamente, compartilhando planos e retry em `application/`.
- **Enviar todo frame à thread de UI.** Uma taxa visual limitada mantém a janela responsiva; captura preserva todos os frames e o último snapshot apresentado permanece atual.

## Validação prevista

```bash
python -m pytest -q
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_gui_smoke.py
ruff check .
ruff format --check .
mypy src/zonepad
python scripts/sync_ai_assets.py --check
zonepad --help
zonepad-gui --help
QT_QPA_PLATFORM=offscreen zonepad-gui --smoke
```

Testes e smoke usam fakes e ambiente offscreen; a revisão desta decisão não acessa hardware.

## Referências

- [`docs/specs/gui-v1.md`](../specs/gui-v1.md)
- [`docs/specs/wizard-v1.md`](../specs/wizard-v1.md)
- [`docs/specs/metrics-v1.md`](../specs/metrics-v1.md)
- [`docs/specs/device-discovery-v1.md`](../specs/device-discovery-v1.md)
- ADRs 0002–0007.
