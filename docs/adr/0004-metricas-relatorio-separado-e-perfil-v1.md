# ADR 0004 — Métricas em relatório separado e perfil `schema_version=1` intacto

- **Status:** aceito
- **Data:** 2026-10-24
- **Spec:** `docs/specs/metrics-v1.md` (aprovada, P1–P8 conforme as recomendações)

## Contexto

O comando `zonepad measure` calcula métricas de sticks e triggers (ruído, drift, range, circularidade, linearidade, histerese, taxa) a partir de uma captura raw segmentada por um manifesto. Essas métricas servem a duas finalidades: documentar a qualidade da medição e derivar os campos que o perfil já suporta (centro, range, deadzone, repouso/fundo de trigger).

O perfil `schema_version=1` é estrito: `CalibrationProfile.from_dict` rejeita campos desconhecidos (`src/zonepad/domain/profile.py`). O `zonepad run` e o `JsonProfileStore` dependem desse contrato. O `load_capture` usado por `zonepad replay` aceita valores que a medição não pode aceitar (timestamps float ou string, `NaN`, canais sem tipo verificado).

O perfil v1 exige dois sticks e dois triggers (`left` e `right`). Controles sem trigger analógico (por exemplo, Switch Pro com ZL/ZR digitais) não produzem esses valores.

## Decisão

1. **Perfil v1 intacto.** `CalibrationProfile` não ganha campo novo; `schema_version` permanece `1`. `build_profile_from_metrics` grava apenas centro, ranges, deadzone (`cut`), curva `linear`, `invert=false`, `rest`/`max` de trigger e `notes` (até 2000 caracteres, com origem e avisos de qualidade).
2. **Relatório separado e versionado.** O relatório de métricas é um artefato próprio com `report_kind="calibration-metrics"` e `metrics_schema_version=1`. A leitura e a escrita validam o schema de forma estrita (campos desconhecidos rejeitados, números finitos, `allow_nan=False`). O Markdown deriva do JSON validado e não recalcula nada. Qualquer mudança incompatível do relatório incrementa `metrics_schema_version`.
3. **Controles sem trigger analógico (P3).** O v1 não os suporta: `measure` reporta `MISSING_TRIGGER_SEGMENT` (error), não gera perfil e sai com código 4 quando `--save-profile` é pedido. Permitir triggers opcionais exige um perfil `schema_version=2` e fica como caminho futuro (ver Alternativas).
4. **Leitor de captura estrito próprio.** `infrastructure/capture_reader.py` valida cada linha (inteiros JSON, sem `NaN`/`Infinity`, `device_id` único, timestamps não decrescentes, campos desconhecidos rejeitados) e cita arquivo e linha. `load_capture` e o `replay` permanecem inalterados.
5. **Manifesto e thresholds com versão própria.** O manifesto (`manifest_version=1`) e o arquivo de thresholds (`thresholds_version=1`) são lidos de forma estrita, com limites de tamanho (1 MiB e 64 KiB), e o relatório registra os thresholds efetivos.
6. **Normalização pelo mapping (P1).** `--mapping` é obrigatório e usa o mesmo JSON v1 do `zonepad run` (ADR 0003); o perfil derivado vive no espaço normalizado em que o runtime o aplica.

## Consequências

- `zonepad run`, `replay`, `profiles`, `list` e os perfis já salvos permanecem compatíveis; nenhuma migração é necessária.
- Pior caso, drift, ruído e demais métricas não são persistidos no perfil. Ficam no relatório e, resumidamente, em `notes`.
- A camada `domain` ganha `metrics.py`, `quality.py`, `findings.py` e `protocol.py` (stdlib apenas, sem IO). A orquestração mora em `application/measure.py`, `application/report.py` e `application/calibration.py`; os leitores e a escrita atômica ficam em `infrastructure/`.
- `build_profile` permanece como caminho legado (média, `min`/`max` e epsilon) e é marcado como tal; a derivação medida nunca usa epsilon e falha com erro acionável.
- Os defaults (fator 1,5; pisos 0,02 e 0,01; mínimos de amostra; thresholds) são *default a validar* até existir captura real assinada por `controller-hardware`.
- Linearidade e histerese usam o tempo normalizado como proxy do curso; seus achados têm severidade `info` (D11, P4).

## Alternativas consideradas

- **Persistir métricas no perfil (schema v2).** Rejeitada para o v1: exige migração v1 → v2, atualização do `run` e do README, e mistura diagnóstico com configuração aplicada. Reabrir se o wizard (prompt 03) precisar comparar sessões a partir do perfil.
- **Trigger opcional no perfil (P3 opção b) ou preenchimento `rest=0, max=1` (opção c).** A opção (b) exige o schema v2 acima; a opção (c) grava valores que não foram medidos. Ambas ficam fora do v1.
- **Estender `load_capture` com validação estrita.** Rejeitada: mudaria o comportamento de `zonepad replay` e de capturas já gravadas.
- **Inferir segmentos por heurística (sem manifesto).** Rejeitada: a medição deixaria de ser reproduzível.
- **Medir os ranges na própria captura (sem mapping).** Rejeitada: seria circular, pois mediria o range que normaliza a captura.
