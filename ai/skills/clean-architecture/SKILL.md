---
name: clean-architecture
description: "Aplica a regra de dependência e boundaries de Clean Architecture: domínio puro, casos de uso, portas e adaptadores, composição na borda e frameworks como detalhes. Use ao estruturar módulos, revisar acoplamentos ou decidir onde uma regra mora."
metadata:
  owner: python-engineer
  version: "1.0"
---

# Clean Architecture

## Quando usar

Use esta skill ao:

- criar ou reorganizar módulos;
- decidir onde uma regra de negócio deve morar;
- revisar acoplamento entre domínio, UI e infraestrutura;
- definir portas e adaptadores;
- planejar testes sem hardware ou banco.

Para o layout concreto do ZonaPad, use também `python-app-architecture`.

## Regra de dependência

As dependências de código apontam para dentro:

```text
interface → application → domain
infrastructure → application/domain (implementa portas)
```

O domínio não conhece UI, banco, SDL, HID, HTTP ou sistema operacional. A aplicação conhece o domínio e define portas. A infraestrutura implementa portas. A interface compõe e apresenta.

## Camadas

| Camada | Contém | Não contém |
| --- | --- | --- |
| Domínio | Entidades, objetos de valor, regras, métricas, invariantes | I/O, UI, framework, logging de infraestrutura |
| Aplicação | Casos de uso, orquestração, portas, DTOs de aplicação | Detalhes de SDL/HID, SQL, widgets |
| Adaptadores de interface | Controllers, presenters, view-models, CLI | Regra de negócio |
| Infraestrutura | SDL3, HIDAPI, evdev, JSON, relógio real, filesystem | Regra de negócio |
| Composição | `main`, CLI, GUI que liga implementações | Lógica de domínio |

## Portas e adaptadores

Defina a porta pelo que o app precisa, não pelo que a biblioteca oferece:

```python
from typing import Protocol


class ProfileStore(Protocol):
    def load(self, profile_id: str) -> Profile: ...
    def save(self, profile: Profile) -> None: ...


class CalibrateDevice:
    def __init__(self, session: DeviceSession, store: ProfileStore) -> None:
        self._session = session
        self._store = store

    def execute(self) -> Profile: ...
```

O caso de uso depende de `ProfileStore`, não de `JsonProfileStore`. O adaptador concreto é injetado na borda.

## O que pertence aonde

| Responsabilidade | Camada |
| --- | --- |
| Normalizar um eixo | Domínio |
| Aplicar deadzone e curva | Domínio |
| Calcular ruído/circularidade | Domínio |
| Orquestrar uma sessão de captura | Aplicação |
| Decidir quando salvar o perfil | Aplicação |
| Ler relatório HID | Infraestrutura |
| Serializar perfil em JSON | Infraestrutura |
| Receber clique do usuário | Interface |
| Formatar uma mensagem de erro | Interface |
| Escolher implementações concretas | Composição |

## Cruzando boundaries

- Use DTOs na fronteira e mapeie para o domínio.
- Não vaze tipos de SDL/HID/ORM para `application` ou `domain`.
- Não use entidade de ORM como entidade de domínio.
- Valide dados na borda; mantenha invariantes no domínio.
- Evite passar `dict` genérico por muitas camadas; prefira tipos explícitos.
- Não deixe a UI chamar infraestrutura diretamente.

## Composition root

A borda monta o grafo:

```python
def main() -> int:
    backend = Sdl3Backend()
    store = JsonProfileStore(path=...)
    use_case = CalibrateDevice(session=backend.open(...), store=store)
    return run_cli(use_case)
```

Evite service locator, singletons globais e imports de infraestrutura dentro do domínio.

## Testabilidade

- Domínio: testes puros, rápidos, sem I/O.
- Aplicação: fakes de portas e relógio injetado.
- Infraestrutura: testes de contrato com o mesmo conjunto de casos.
- Interface: testes de view-model ou de contrato, não de pixels.
- CI: sem hardware real, rede ou banco externo.

## Erros comuns

- **Cargo cult de pastas:** separar diretórios sem respeitar a regra de dependência.
- **Domínio anêmico:** regras espalhadas em services, UI ou adaptadores.
- **Caso de uso que importa UI:** a dependência aponta para fora.
- **Framework no centro:** tipos de SDL/HID/ORM atravessam o domínio.
- **Dependência circular:** módulos se importam mutuamente.
- **Abstração prematura:** uma porta para cada função, sem variação real.
- **DTO igual à entidade:** a fronteira não protege nada.

## Aplicação no ZonaPad

- **Domínio:** `RawFrame`, `NormalizedFrame`, `CalibratedFrame`, métricas, perfil, normalização e curvas.
- **Aplicação:** `DeviceBackend`, `DeviceSession`, `ProfileStore`, casos de uso de detectar/calibrar/capturar.
- **Infraestrutura:** `Sdl3Backend`, `HidBackend`, `ReplayBackend`, `JsonProfileStore`, relógio do sistema.
- **Interface:** CLI, GUI e view-models.
- **Composição:** `interface/cli.py` e o entrypoint da GUI.

O layout detalhado está em `python-app-architecture`.

## Relação com clean-code

`clean-code` cuida da qualidade local: nomes, funções, erros e testes. `clean-architecture` cuida dos boundaries e da direção das dependências. As duas se complementam; nenhuma substitui a outra.

## Checklist

- [ ] As dependências apontam para dentro.
- [ ] O domínio não importa UI, SO, SDL, HID ou persistência.
- [ ] Portas são definidas pela necessidade do app.
- [ ] Adaptadores implementam portas e são injetados na borda.
- [ ] Tipos de framework não cruzam o boundary.
- [ ] A composição acontece em um único ponto.
- [ ] Domínio e aplicação são testáveis sem infraestrutura.
- [ ] Não há abstração prematura nem dependência circular.
