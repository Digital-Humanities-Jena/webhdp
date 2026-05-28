FROM webhdp_clean-backend
USER root
WORKDIR /app
COPY hdp_3d_component_runtime/component_runner.py /app/component_runner.py
ENTRYPOINT ["python", "/app/component_runner.py", "--component", "texture_dependency_auditor"]
