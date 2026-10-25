# ADR 0003 — Mapping JSON autoritativo para o runtime evdev

- **Status:** aceito
- **Data:** 2026-10-24

## Contexto

O runtime Linux precisa normalizar counts evdev antes de aplicar um perfil. Cada eixo requer mínimo, centro e máximo; cada trigger requer repouso e máximo. `EVIOCGABS` descreve limites absolutos, mas não fornece por si só o centro de calibração nem o repouso que o ZonaPad precisa aplicar de forma reproduzível.

Também é necessário traduzir códigos evdev físicos em nomes semânticos para o publisher uinput, sem levar códigos Linux ao domínio.

## Decisão

O `zonepad run` recebe um mapping JSON de `schema_version=1` como fonte autoritativa para:

- os códigos dos eixos `lx`, `ly`, `rx` e `ry`;
- os códigos dos triggers `lt` e `rt`;
- `minimum`, `center` e `maximum` dos sticks;
- `rest` e `maximum` dos triggers;
- um subconjunto opcional de botões físicos para os quatro nomes semânticos faciais.

O parser rejeita campos desconhecidos, códigos repetidos, tipos inválidos e ranges impossíveis. `--mapping` continua opcional no parser, mas a execução sem ele falha com código 2 e mensagem acionável; o runtime não inventa centro ou repouso. A consulta `EVIOCGABS` permanece fora deste incremento e poderá ser avaliada como fonte complementar em ADR futuro.

O adaptador evdev acumula eventos até `EV_SYN/SYN_REPORT` e só então emite `RawFrame`. A estrutura `input_event` usa valor signed de 32 bits. O publisher uinput anuncia mínimo zero para os triggers virtuais.

## Consequências

- O pipeline permanece determinístico e testável com fakes, sem `/dev/input` ou `/dev/uinput` na CI.
- O usuário precisa obter e manter um mapping por dispositivo/modo/firmware.
- Ranges raw não são assumidos como universais; a documentação inclui apenas um exemplo.
- Suporte a dispositivos sem mapping e detecção automática de capabilities ficam para incrementos posteriores.
