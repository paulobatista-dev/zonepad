# Changelog

Este arquivo segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
O projeto ainda não publicou uma versão.

## [Não publicado]

### Adicionado

- Fluxo de descoberta de controles, identidade estável, catálogo de famílias e
  geração de mappings por dispositivo.
- Interface gráfica PySide6 opcional para acompanhar e orientar calibração.
- Ambiente reprodutível de desenvolvimento, cobertura, build e validação de
  instalação de wheel.

### Alterado

- CLI, documentação e testes ampliados para descoberta, métricas, perfis e GUI.

## [0.1.0] - 2026-10-25

### Adicionado

- MVP Linux de calibração guiada de gamepads, com pipeline raw → normalizado →
  calibrado, replay determinístico, perfis JSON versionados e interface CLI.
- Métricas de sticks e triggers, relatório de qualidade e wizard de captura.
- Descoberta de dispositivos, mappings por família e interface PySide6 opcional.
