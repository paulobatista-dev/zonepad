# ADR 0002 — MVP Linux com pipeline puro e portas de hardware

- **Status:** aceito
- **Data:** 2026-10-24

## Contexto

O aplicativo precisa aplicar perfis de calibração a entradas físicas e expor uma saída virtual sem tornar o domínio dependente de Linux, evdev ou Qt.

## Decisão

O domínio implementa `RawFrame`, `NormalizedFrame`, `CalibratedFrame`, normalização por ranges medidos e a ordem center → range → deadzone → curve → invert. A aplicação define portas `DeviceSession`, `DeviceBackend`, `ProfileStore` e `FramePublisher`. Adaptadores Linux ficam em `infrastructure`; replay/fakes sustentam testes sem hardware. A GUI PySide6 é opcional.

## Consequências

O pipeline é testável e mantém o domínio portátil; o MVP Linux registra um dispositivo uinput e publica eventos calibrados, enquanto a composição ainda fornece os mapeamentos evdev e ranges medidos. Desconexão e timeout permanecem estados distintos.
