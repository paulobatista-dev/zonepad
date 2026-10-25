# Matriz de dispositivos e backends

Esta matriz é um ponto de partida. Preencha os campos com dados da sua captura; não trate valores como universais.

## Campos a levantar

| Campo | Como obter | Por que importa |
| --- | --- | --- |
| `vid`/`pid` | SDL, HIDAPI, evdev, Raw Input | Identidade e seleção de parser |
| Nome/fabricante | API do backend | Exibição e desambiguação |
| GUID SDL | SDL3 | Mapping estável entre plataformas |
| Serial | API/relatório | Distinguir unidades idênticas |
| Backend | Decisão de integração | Afeta ranges, permissões e raw |
| Report ID/tamanho | Captura HID | Parsing seguro |
| Eixos | Captura | Quantidade, sinal, resolução |
| Triggers | Captura | Analógicos? faixa? repouso? |
| Botões/hat | Captura | Mapeamento e debounce |
| Taxa nominal | Teste de 5 s | Comparar taxa efetiva |
| Deadzone de firmware | Captura em repouso e movimento lento | Não aplicar deadzone dupla |
| Rumble/haptics | Capabilities | Feedback do wizard |
| Giroscópio/acelerômetro | Capabilities | Escopo futuro; não assumir |

## Dispositivos alvo

| Família | Backend principal | Backend raw | Observações a validar |
| --- | --- | --- | --- |
| Xbox (XInput) | SDL3 | Raw Input/HID | Triggers separados no raw; XInput combina |
| Xbox (Bluetooth) | SDL3 | HIDAPI | Latência e reconexão |
| DualShock 4 | SDL3 | HIDAPI | Touchpad/gyro opcionais; validar report |
| DualSense | SDL3 | HIDAPI | Adaptive triggers/haptics exigem protocolo específico |
| Switch Pro | SDL3 | HIDAPI | Mapping e botões variam por modo |
| 8BitDo | SDL3 | HIDAPI | Modos DInput/XInput/Switch mudam o report |
| HID genérico | SDL3/HIDAPI | HIDAPI/evdev | Parser configurável ou captura guiada |

## Linux

| Item | Verificação |
| --- | --- |
| Device node | `/dev/input/event*` ou `/dev/hidraw*` |
| Permissão | Grupo `input` ou regra udev; não exigir root no app |
| ABS ranges | `EVIOCGABS` ou equivalente; não assumir |
| Steam Input | Device virtual pode substituir o físico |
| Hot-plug | udev ou rescan com debounce |

## Windows

| Item | Verificação |
| --- | --- |
| XInput | Até 4 controles; triggers combinados |
| Raw Input | Registro por classe HID; foco da janela |
| Exclusividade | Falha ao abrir device em uso |
| Bluetooth | Reconexão e latência |

## macOS

| Item | Verificação |
| --- | --- |
| Permissão | Input Monitoring / entitlements |
| GameController | Perfis e haptics |
| IOKit/HID | Acesso raw e complexidade |
| Bluetooth | Eventos de desconexão |

## Registro de captura

Preencha para cada dispositivo testado:

```text
Dispositivo:
VID/PID:
Backend:
SO/versão:
Conexão (USB/Bluetooth):
Report ID/tamanho:
Eixos (nome, faixa, repouso):
Triggers (faixa, repouso):
Taxa nominal/efetiva:
Deadzone de firmware:
Quirks:
Arquivo de captura:
```
