# Spec — GUI PySide6 v1

- **Status:** aprovada pelo usuário em 2026-10-25; implementação em andamento.
- **Data:** 2026-10-25.
- **Prompt:** [`ai/prompts/05-gui-pyside6.md`](../../ai/prompts/05-gui-pyside6.md).
- **ADR:** [`docs/adr/0008-gui-pyside6-como-adaptador.md`](../adr/0008-gui-pyside6-como-adaptador.md).
- **Base técnica:** wizard v1, métricas v1, descoberta v1 e ADRs 0002–0007.
- **Revisões de design:** controller-hardware (unidades, escalas, instruções e qualidade); python-engineer (arquitetura, integração e testes). Pareceres estáticos; nenhum hardware foi acessado.

## Problema

O ponto de entrada GUI atual cria uma janela com uma etiqueta estática. A pessoa precisa recorrer à CLI para descobrir controles, acompanhar entradas, conduzir a calibração e inspecionar perfis. Esta feature entrega essas tarefas em uma janela Qt que consome os casos de uso existentes.

## Usuário e contexto

Pessoa em Linux com gamepad compatível com descoberta sysfs/evdev e mapping v1. A GUI apresenta dados do dispositivo e conduz o wizard com a mesma state machine, instruções, motor de qualidade e persistência usados pelo CLI.

## Resultado esperado

Uma aplicação PySide6 opcional, iniciada por `zonepad-gui`, com painéis Dispositivos, Monitor, Calibração e Perfis. A aplicação usa view-models Python puros, adapters nas bordas e workers para operações bloqueantes. A CLI e o domínio continuam importáveis quando PySide6 está ausente.

## Escopo

- Janela principal e navegação por teclado entre os quatro painéis.
- Descoberta e seleção por `StableIdentity`, status de mapping, atualização manual e watch por `QTimer`.
- Monitor somente leitura de sticks, triggers e botões em valores normalizados.
- Wizard gráfico dirigido por `WizardPhase`, `step`, planos compartilhados, `MeasureRunner`, `Finding` e `ProfileStore` existentes.
- Lista e detalhe somente leitura de perfis, isolando erros por perfil.
- Entry point `zonepad-gui`, flags `--help`, `--version` e `--smoke`.
- Testes Qt em `offscreen`, testes puros dos view-models e testes com fakes sem hardware.
- Spec, ADR 0008, README, `ai/prompts/README.md` e documentação de uso após aprovação; o handoff de `ai/` vai para `prompt-engineer`.

## Fora de escopo

- Aplicação de perfil ao monitor ou runtime nesta versão; o monitor apresenta a camada normalizada.
- Edição e exclusão de perfis, criação de mapping draft na GUI e múltiplas sessões simultâneas.
- Windows/macOS, novos backends, uinput, temas avançados, vídeo e visualização 3D.
- Alterações em fórmulas, thresholds, schema de mapping/perfil ou política de retry.
- Publicação, merge e release.

## Requisitos funcionais

### RF1 — Aplicação e navegação

1. `zonepad-gui` cria uma instância de `QApplication` na composição de `gui/app.py` e uma `QMainWindow` com `QStackedWidget`.
2. A navegação expõe Dispositivos, Monitor, Calibração e Perfis em português e mantém a seleção atual entre painéis.
3. `run(argv: Sequence[str] | None = None) -> int` valida `--help`, `--version` e `--smoke` antes do import de Qt.
4. O extra `gui` permanece opcional (`PySide6>=6.7`). A ausência do binding no entry point apresenta comando de instalação em PT-BR e exit code 2; `import zonepad` e `zonepad --help` continuam disponíveis.
5. `--smoke` constrói a janela, processa eventos em modo headless e retorna 0.

### RF2 — Dispositivos e mapping

1. O painel lista `snapshot.gamepads` por ID estável, nome, VID:PID, conexão, nó de diagnóstico, estado do mapping e avisos de fragilidade.
2. Atualizar chama `discover_devices`; watch usa `PollingHotplugWatcher` e `QTimer` com intervalo validado por `validate_poll_interval`.
3. A seleção guarda `StableIdentity`; `eventN` é apresentado como diagnóstico.
4. Mapping ausente/inválido permanece visível como estado do dispositivo e bloqueia Monitor e Calibração, pois o backend evdev decodifica canais pelo mapping. Ambos os painéis oferecem a ação `zonepad mapping draft --device <id>`.
5. Uma identidade frágil exige confirmação explícita antes da calibração.
6. Falta de permissão apresenta orientação ACL/grupo `input` com impacto explicado e sem executar comandos privilegiados.

### RF3 — Monitor

1. O monitor abre uma sessão somente leitura. Um caso de uso de aplicação recebe `RawFrame`, usa `normalize_frame` e publica `NormalizedFrame` imutável; o widget apresenta o último snapshot recebido.
2. Sticks mostram `lx/ly` e `rx/ry` em plano cartesiano, com cada eixo no intervalo `[-1, 1]`, origem identificada e marca de centro.
3. A coordenada Y visual usa positivo para cima, enquanto o texto numérico conserva o valor e o sinal de `ly`/`ry` recebido do modelo.
4. Triggers `lt`/`rt` aparecem em barra com intervalo `[0, 1]` e indicação de repouso do mapping. Quando o mapping está provisório, a tela informa que essa referência é provisória.
5. Botões definidos no mapping aparecem com rótulos espaciais dentre `south/east/north/west`. Cada botão mapeado mostra pressionado quando seu nome está em `NormalizedFrame.buttons` e solto nos demais frames. Mapping com `buttons` vazio apresenta o estado textual “Nenhum botão mapeado”.
6. Cada painel informa `Camada: normalizada`; a apresentação padrão usa essa camada. Valores raw em counts ficam nos fluxos de captura/diagnóstico. Taxa observada de frames é calculada como `Hz = (n - 1) / (t_último - t_primeiro)` sobre timestamps distintos na janela móvel mais recente de 1 s e apresentada quando pelo menos dois frames estão disponíveis.
7. Coalescência de apresentação mantém o snapshot mais recente em até 30 atualizações visuais por segundo. A leitura roda no worker.
8. Desconexão apresenta estado de erro e ação para retornar à seleção e atualizar a lista.

### RF4 — Wizard

1. Fases são conduzidas por `WizardPhase` e `step`; efeitos são executados por um coordenador da interface.
2. Planos e instruções compartilhados ficam em `application/`; CLI e GUI consomem a mesma fonte. Os defaults permanecem: warmup 2 s, repouso 5 s com 1 s interno, círculo 6 s por direção e trigger 25 s.
3. A GUI apresenta instrução, duração orientativa, contagem regressiva, progresso, tempo restante e segmento atual.
4. Captura grava todos os frames recebidos, independentemente da coalescência visual do monitor.
5. A aplicação define uma porta de medição do wizard; a composição conecta essa porta ao `MeasureRunner` de infraestrutura. A tela apresenta status e findings devolvidos pelo motor, com mensagem, código, severidade e métrica.
6. Um valor de finding é exibido com unidade/contexto correspondente à métrica; quando a UI não dispõe de contexto seguro, apresenta mensagem, código e caminho da métrica.
7. Retry segue `STRICT_BLOCKING`, os alvos elegíveis e os limites de wizard v1: dois por alvo e seis globais. A função de resolução de alvos fica em `application/` e é compartilhada com o CLI.
8. Cancelamento executa abort idempotente, preserva artefatos parciais e retorna ao resumo.
9. Salvamento chama `ProfileStore` apenas para perfil derivável e aceito; sucesso apresenta `profile_id`.
10. `WizardState` atual permanece o reducer de fase. Seleção, mapping, outcome, artifacts e contadores detalhados vivem em um contexto imutável do workflow na borda; eventos retornam ao reducer sem armazenar objetos de infraestrutura.

### RF5 — Perfis

1. A aplicação expõe uma porta de listagem de perfis; o adapter `JsonProfileStore` enumera IDs via `list_profiles()` e carrega cada perfil de forma independente.
2. A linha de cada perfil exibe ID, nome do dispositivo, VID:PID, data e resumo de centros, ranges, deadzone, repouso/máximo de triggers e notas disponíveis.
3. Perfil inválido/ilegível mantém a lista disponível e recebe motivo e nome do arquivo relativo ao diretório configurado.
4. Detalhes são somente leitura.

### RF6 — Erros e recuperação

| Situação | Estado apresentado | Ação |
|---|---|---|
| PySide6 ausente | mensagem de instalação no terminal, exit 2 | instalar `.[gui]` |
| Nenhum gamepad | estado vazio | atualizar e abrir instruções de diagnóstico CLI |
| Dispositivo desconectado | banner e monitor bloqueado | voltar à seleção e atualizar |
| Permissão negada | causa e dispositivo identificados | consultar ACL ou considerar grupo `input`, com impacto explicado |
| Mapping ausente | estado do mapping em Dispositivos, Monitor e Calibração | gerar draft pela CLI sugerida |
| Mapping inválido | detalhe de validação em Dispositivos, Monitor e Calibração | validar/corrigir arquivo pela CLI sugerida |
| Identidade frágil | confirmação contextual | confirmar controle selecionado |
| Captura ou medição falha | fase e motivo acionável | repetir quando a política permitir ou encerrar com resumo |
| Perfil inválido | erro isolado por item | inspecionar nome do arquivo relativo à pasta configurada; demais perfis seguem acessíveis |
| Plataforma gráfica indisponível | mensagem de inicialização controlada | verificar plataforma/configuração Qt e orientar configuração de display; `offscreen` fica reservado a testes e smoke |

Mensagens em PT-BR apresentam causa e próxima ação. Diagnósticos de tela mostram caminhos relativos; detalhes técnicos estruturados seguem para stderr.

## Requisitos não funcionais

- View-models usam dataclasses imutáveis e APIs Python sobre os modelos de aplicação/domínio; acesso Qt e dispositivos permanece nos adapters.
- Qt, descoberta, persistência e montagem de backends ficam em adapters/composição na borda.
- `DeviceSession.read` e captura executam fora da thread de UI; sinais transportam snapshots imutáveis.
- Um worker de leitura atende uma sessão. O dono do lifecycle coordena a thread já existente de `LiveCaptureSession` para evitar workers de leitura duplicados.
- Ao fechar, a aplicação para timers, sinaliza cancelamento, fecha a sessão e aguarda encerramento por até 2 s. Operações de leitura usam timeout para permitir encerramento cooperativo.
- Widgets de sticks, triggers e botões usam `QPainter`, com PySide6 como dependência gráfica do extra `gui`.
- Tab order, nomes acessíveis, atalhos Ctrl+R/Esc, foco coerente, fontes escaláveis e sinais textuais acompanham as cores e ícones.
- O sistema de testes usa `QT_QPA_PLATFORM=offscreen`, uma fixture própria de `QApplication` e `QSignalSpy`.

## Modelo de dados e unidades

| Apresentação | Tipo/fonte | Unidade/faixa | Camada |
|---|---|---|---|
| Sticks | `NormalizedFrame.axes` | adimensional `[-1, 1]` por eixo | normalizada |
| Triggers | `NormalizedFrame.triggers` | adimensional `[0, 1]` | normalizada |
| Botões mapeados | `NormalizedFrame.buttons` | estado discreto pressionado/solto, rótulos espaciais | estado discreto mapeado |
| Duração/progresso | `SegmentPlan`, `CaptureSession` | segundos e fração `[0, 1]` | execução do protocolo |
| Findings | `Finding`/relatório | unidade definida pelo caminho da métrica; proporção adimensional quando aplicável | resultado do motor |
| Perfil | `CalibrationProfile` | centros/ranges/deadzone normalizados; trigger rest/max `[0, 1]` | configuração persistida |

`RawFrame` guarda valores inteiros de evdev em counts e timestamps monotônicos em ns; um caso de uso de aplicação chama `normalize_frame` antes de alimentar o monitor. A GUI apresenta os botões semânticos presentes no mapping, inclusive estado vazio quando nenhum canal de botão está configurado. `CalibratedFrame` preserva as faixas normalizadas após `apply_profile`; sua apresentação fica para uma versão com aplicação de perfil. Widgets e view-models formatam valores; aplicação/domínio convertem raw→normalizado e o motor existente deriva qualidade.

## Impacto por camada

- **Domain:** fórmulas e schemas existentes permanecem como contratos; seus tipos são fontes das unidades exibidas.
- **Application:** novo módulo de planos/textos compartilhados e função de alvos de retry; portas de monitor normalizado, execução de medição e listagem de perfis; workflow atualiza o reducer existente.
- **Infrastructure:** adapters usam scanner, mapping store, `ProfileStore`, backend, captura e `MeasureRunner`; dados externos continuam validados por seus contratos existentes.
- **Interface:** `gui/` recebe composição Qt, janela, view-models, adapters, workers, widgets e painéis. `calibration_cli.py` passa a consumir planos e retry compartilhados.
- **Packaging:** extra `gui` mantém `PySide6>=6.7`; o ambiente de design instalou PySide6 6.12.0 em Python 3.15.0.
- **Persistência:** perfil schema v1; GUI cria perfis pelo fluxo de calibração e lista perfis existentes.

## Impacto em hardware/dispositivos

Semântica revisada estaticamente por `controller-hardware`. Valores exibidos vêm de frames normalizados; range de stick é `[-1,1]` e trigger `[0,1]`. A coordenada gráfica y é invertida no plano cartesiano convencional para manter positivo para cima, enquanto o valor numérico conserva o sinal recebido. Botões usam rótulos espaciais `south/east/north/west`, que identificam posição no mapping. Plausibilidade prática e legibilidade serão verificadas em revisão visual; esta especificação usou modelos e fixtures, sem hardware.

## Plano de testes

- View-models puros: estados, comandos, perfil inválido e matriz de erros.
- Widgets com frames sintéticos: centro/extremos de sticks, repouso/máximo de triggers e estados de botões para mapping completo, subconjunto e mapping vazio.
- Descoberta/mapping: dois gamepads, nó auxiliar, mapping ausente/inválido, identidade frágil, refresh e eventos de hot-plug roteirizados.
- Wizard: paridade de fases, instruções, defaults, findings e retry com `tests/test_calibrate_flow.py`; cancelamento, salvamento e falhas com fakes.
- Concorrência: rajada de 1.000 frames mantém último snapshot e taxa visual <= 30 Hz; arquivo de captura mantém todos os frames; evento de UI processa durante leitura; worker encerra em menos de 2 s.
- Qt: `QSignalSpy`, navegação, foco, taxa observada de frames com fórmula explícita e `zonepad-gui --smoke` em `offscreen`.
- Imports: `zonepad`/CLI seguem funcionais sem PySide6; `gui` carrega Qt apenas ao iniciar execução GUI.
- Arquitetura: view-models sem PySide6/SO; somente `app.py` cria `QApplication`; conversão raw→normalizado usa caso de uso; `MeasureRunner` fica atrás da porta de aplicação.
- Suíte completa em ambiente Python 3.15.0 com extras `dev,gui`, usando `offscreen`, fakes, fixtures e relógio injetado; casos de teste usam nenhuma rede e nenhum dispositivo do sistema.

## Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Wheel de PySide6 muda disponibilidade por Python/plataforma | instalação do extra | gate de instalação registrado: PySide6 6.12.0 importável em Python 3.15.0 neste ambiente |
| Fechamento de sessão bloqueado | janela demora a encerrar | timeout de leitura, cancelamento cooperativo e teste de shutdown de 2 s |
| Coalescência altera perceção temporal | atualização visual reduzida | taxa documentada e último frame prevalece; captura conserva todos os frames |
| Direção gráfica de Y diverge de convenção de usuário | leitura visual confusa | legenda explícita e teste de sinal nos rótulos/valores |
| Mensagem de finding perde unidade | interpretação errada | contexto por métrica e teste de apresentação |
| Wayland/X11 variam em foco e aparência | ergonomia diferente | testes offscreen e checklist manual posterior |
| Recursos de acessibilidade variam por ambiente | navegação assistiva parcial | accessible names, teclado, foco e revisão manual declarados |
| Camada de perfil confundida com entrada observada | leitura visual incorreta | v1 exibe somente NormalizedFrame; painel de perfis oferece inspeção somente leitura |

## Critérios de aceite

- `import zonepad` e `zonepad --help` funcionam sem o extra GUI; `zonepad-gui --help` valida argumentos antes da inicialização Qt.
- `zonepad-gui` sem extra GUI retorna 2 com orientação de instalação e diagnóstico de terminal acionável.
- `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke` retorna 0.
- Os quatro painéis são navegáveis por teclado e preservam seleção.
- Seleção usa ID estável e lista VID:PID, conexão, nó e status de mapping.
- Monitor declara camada, exibe stick em `[-1,1]`, trigger em `[0,1]` e botões com texto.
- Worker mantém UI responsiva; apresentação limita-se a 30 Hz; captura mantém todos os frames.
- Mapping ausente/inválido bloqueia Monitor e Calibração com ação de recuperação; identidade frágil exige confirmação antes de calibrar.
- Wizard partilha planos/textos/retry com CLI e usa o reducer e o motor de qualidade existentes.
- Findings mostram contexto suficiente; retry segue política v1.
- Cancelamento preserva artefatos parciais; salvamento grava perfil v1 válido e apresenta UUID.
- Perfil inválido fica isolado por item.
- Fechar janela encerra worker e sessão em menos de 2 s.
- Toda classe da matriz de erros tem mensagem e ação.
- Testes Qt passam em `offscreen`; suíte completa passa sem hardware.
- README documenta instalação, fluxo e limites; `docs/adr/0008-...md` aprovado junto com esta spec antes de implementação.

## Decisões aceitas D1–D12

| ID | Decisão proposta | Dono |
|---|---|---|
| D1 | Binding opcional único: `PySide6>=6.7`; versão observada 6.12.0; imports tardios e saída 2 acionável | Python |
| D2 | Widgets próprios com `QPainter` | Python |
| D3 | Uma `QApplication`, uma `QMainWindow`, quatro páginas em `QStackedWidget` | Python |
| D4 | Worker cooperativo, sinais imutáveis, coalescência visual 30 Hz, captura integral, shutdown em 2 s | Python |
| D5 | Planos, textos e alvos de retry compartilhados em `application/`; CLI e GUI equivalentes | Python |
| D6 | Descoberta atual e mapping store via use cases; seleção por identidade; watch por `QTimer`; caso de uso transforma RawFrame em NormalizedFrame para monitor | Python |
| D7 | Porta de aplicação lista perfis via adapter JSON; perfis são inspecionados; monitor v1 mostra camada normalizada | Python + produto |
| D8 | Testes puros e Qt offscreen com fixture própria e `QSignalSpy` | Python |
| D9 | PT-BR, teclado, tab order explícita, accessible names, fontes escaláveis e estado textual | Python |
| D10 | Extra `gui` opcional; import de Qt na borda; `--help`, `--version`, `--smoke` | Python |
| D11 | Erro → estado → ação; detalhe por item com caminho relativo; logs estruturados em stderr | Python |
| D12 | Linux, um dispositivo, monitor somente leitura, sem runtime de perfil, edição/exclusão ou temas avançados | Principal |

## Validações posteriores

- Revisão humana da acessibilidade e apresentação visual em desktop após a implementação.
