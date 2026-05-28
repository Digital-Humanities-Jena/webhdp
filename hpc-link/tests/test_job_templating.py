import unittest
from app.services.job_templating import job_template_service
from app.schemas.job import JobConfig

class TestJobTemplating(unittest.TestCase):

    def test_render_simple_job(self):
        config = JobConfig(
            job_name="test_job",
            commands=["echo 'Hello World'"]
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("#SBATCH --job-name=test_job", script)
        self.assertIn("#SBATCH --partition=partition-a", script) # Default
        self.assertIn("echo 'Hello World'", script)
        self.assertNotIn("--gres=gpu", script) # No GPU requested

    def test_render_gpu_job(self):
        config = JobConfig(
            job_name="gpu_job",
            gpu_type="a100",
            gpu_count=2,
            commands=["nvidia-smi"]
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("#SBATCH --gres=gpu:a100:2", script)

    def test_render_environment_and_modules(self):
        config = JobConfig(
            job_name="env_job",
            modules=["python/3.11", "cuda/12.1"],
            environment_vars={"MY_VAR": "123", "DEBUG": "true"},
            commands=["printenv"]
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("module load python/3.11", script)
        self.assertIn("module load cuda/12.1", script)
        self.assertIn("export MY_VAR=123", script)
        self.assertIn("export DEBUG=true", script)

    def test_working_dir(self):
        config = JobConfig(
            job_name="wd_job",
            working_dir="/work/project",
            commands=["ls -la"]
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("cd /work/project", script)

    def test_uv_integration(self):
        config = JobConfig(
            job_name="uv_job",
            commands=["python main.py"],
            use_uv=True,
            uv_install=True
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("Initializing UV environment", script)
        self.assertIn("uv venv", script)
        self.assertIn("source .venv/bin/activate", script)
        self.assertIn("uv sync", script)

        self.assertIn("uv sync", script)

    def test_webhook_generation(self):
        config = JobConfig(
            job_name="hook_job",
            commands=["echo done"],
            webhook_url="https://example.com/callback"
        )
        script = job_template_service.render_sbatch(config)

        self.assertIn("curl -X POST", script)
        self.assertIn("https://example.com/callback", script)
        self.assertIn("$SLURM_JOB_ID", script)

if __name__ == '__main__':
    unittest.main()
