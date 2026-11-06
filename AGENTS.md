# AGENTS.md

Репозиторий-компаньон mlxini: собирает образ `mlxini-ch341i2c`
(CH341 USB↔I2C). Ремоут github — только через PR: прямой пуш в master
авто-ревертит master-guard.

## Кодовые правила

- **no-cre-hardcode.** Контейнерный инструмент определяется переменной
  `CRE` (`podman` или `podman-remote`): из toolbx (есть
  `/run/.containerenv`) сборка идёт через хост. Не хардкодить
  `podman`/`podman-remote` в Makefile и скриптах.
- **rm-rf-guard.** `rm -rf` по пути из переменной — только через
  `scripts/safe-rm --under ROOT TARGET...` (копия из llm-rig):
  только абсолютные пути; таргет удаляется, только если равен ROOT или
  лежит под ним; mount point (включая `/`) никогда не удаляется.
- **english-commits.** Сообщения коммитов git — на английском.
