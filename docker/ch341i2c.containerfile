FROM registry.fedoraproject.org/fedora:44

RUN dnf install -y python3 python3-pyusb \
    && dnf clean all

COPY scripts/ch341i2c.py /usr/local/bin/ch341i2c
RUN chmod +x /usr/local/bin/ch341i2c

COPY scripts/ch341i2c.py /tmp/ch341i2c-module.py
RUN PURELIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && mkdir -p "$PURELIB" \
    && cp /tmp/ch341i2c-module.py "$PURELIB/ch341i2c.py" \
    && rm -f /tmp/ch341i2c-module.py

ENTRYPOINT ["/usr/local/bin/ch341i2c"]
