ifeq ($(shell test -f /run/.containerenv && echo y),y)
CRE ?= podman-remote
HOSTCURDIR := $(patsubst /run/host/%,%,$(CURDIR))
else
CRE ?= podman
HOSTCURDIR := $(CURDIR)
endif

CH341_IMAGE ?= mlxini-ch341i2c

-include local.mk

.PHONY: image test

image:
	$(CRE) build -f docker/ch341i2c.containerfile -t $(CH341_IMAGE) .

test:
	python3 -m pytest tests/
