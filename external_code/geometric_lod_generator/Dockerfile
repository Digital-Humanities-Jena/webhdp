FROM debian:trixie-slim
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends blender python3-numpy python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
RUN blender --background --factory-startup --python-use-system-env --python-exit-code 1 --python-expr 'import numpy; print(numpy.__version__)'
WORKDIR /app
COPY hdp_3d_component_runtime/component_runner.py /app/component_runner.py
COPY geometric_lod_generator/runner.py /app/geometric_lod_runner.py
COPY geometric_lod_generator/blender_entry.py /app/blender_entry.py
COPY mesh_optimizer/runner.py /app/glb_contract.py
ENTRYPOINT ["python", "/app/component_runner.py", "--component", "geometric_lod_generator"]
