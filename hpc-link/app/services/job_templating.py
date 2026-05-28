import os
import shlex
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from app.schemas.job import JobConfig

class JobTemplateService:
    def __init__(self, template_dir: str = None):
        if not template_dir:
            # Default to app/templates
            current_dir = Path(__file__).resolve().parent
            template_dir = current_dir.parent / "templates"

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )
        self.env.filters["shell_quote"] = shlex.quote

    def render_sbatch(self, config: JobConfig) -> str:
        """
        Render a SLURM sbatch script from the configuration.
        """
        template = self.env.get_template("slurm/base.sh.j2")
        return template.render(config=config)

# Singleton instance? Or just instantiate when needed.
# For now, let's keep it simple.
job_template_service = JobTemplateService()
