# ch341i2c-container

Компаньон репозитория [mlxini](https://github.com/wipe-coading-survivors/mlxini):
образ `mlxini-ch341i2c` — CLI `ch341i2c` (CH341 USB↔I2C, PACBTECH SFP
Programmer 1a86:5512) и python-модуль `ch341i2c` в site-packages контейнера.

## Сборка и тесты

```sh
make image    # docker/ch341i2c.containerfile -> тег mlxini-ch341i2c
make test     # pytest: тесты фрейминга I2C
```

Тег образа переопределяется через `local.mk` (см. `local.mk.example`).

## Контракт потребления (mlxini)

- mlxini монтирует своё дерево в контейнер: `-v <mlxini>:/work`.
- CLI: `podman run --rm --privileged -v <mlxini>:/work mlxini-ch341i2c --addr 0x50 read 256`.
- Оверлейные диагностические скрипты mlxini (`/work/scripts/*.py`,
  entrypoint `python3`) делают `import ch341i2c` — модуль резолвится из
  site-packages контейнера, независимо от дерева mlxini.
