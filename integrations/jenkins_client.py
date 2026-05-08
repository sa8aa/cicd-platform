"""
Jenkins API client — creates jobs, triggers builds, fetches status.
"""
import logging
import xml.etree.ElementTree as ET
from django.conf import settings

logger = logging.getLogger(__name__)

# Pipeline job config XML template
JOB_CONFIG_XML = """<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>{description}</description>
  <keepDependencies>false</keepDependencies>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition"
              plugin="workflow-cps">
    <script>{jenkinsfile}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>"""


class JenkinsClient:
    def __init__(self):
        self.server = None
        try:
            import jenkins
            self.server = jenkins.Jenkins(
                settings.JENKINS_URL,
                username=settings.JENKINS_USER,
                password=settings.JENKINS_TOKEN,
            )
            self.server.get_whoami()   # test connection
            logger.info("Jenkins connected.")
        except Exception as e:
            logger.warning(f"Jenkins not available: {e}")

    def is_connected(self):
        return self.server is not None

    # ── Job management ─────────────────────────────────────────────────────

    def create_or_update_job(self, job_name: str, jenkinsfile: str,
                              description: str = '') -> bool:
        """Create a new Pipeline job or update its Jenkinsfile."""
        if not self.server:
            logger.warning("Jenkins not connected — skipping job create.")
            return False
        try:
            config = JOB_CONFIG_XML.format(
                description=description,
                jenkinsfile=jenkinsfile.replace('&', '&amp;')
                                       .replace('<', '&lt;')
                                       .replace('>', '&gt;'),
            )
            if self.server.job_exists(job_name):
                self.server.reconfig_job(job_name, config)
                logger.info(f"Jenkins job '{job_name}' updated.")
            else:
                self.server.create_job(job_name, config)
                logger.info(f"Jenkins job '{job_name}' created.")
            return True
        except Exception as e:
            logger.error(f"Jenkins create/update job error: {e}")
            return False

    def delete_job(self, job_name: str) -> bool:
        if not self.server:
            return False
        try:
            if self.server.job_exists(job_name):
                self.server.delete_job(job_name)
            return True
        except Exception as e:
            logger.error(f"Jenkins delete job error: {e}")
            return False

    # ── Build management ───────────────────────────────────────────────────

    def trigger_build(self, job_name: str) -> dict:
        """Trigger a build and return queue info."""
        if not self.server:
            return {'mock': True, 'build_number': 0}
        try:
            queue_id = self.server.build_job(job_name)
            return {'queue_id': queue_id}
        except Exception as e:
            logger.error(f"Jenkins trigger error: {e}")
            raise

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        if not self.server:
            return {}
        try:
            return self.server.get_build_info(job_name, build_number)
        except Exception as e:
            logger.error(f"Jenkins build info error: {e}")
            return {}

    def get_build_console(self, job_name: str, build_number: int) -> str:
        if not self.server:
            return "Jenkins non connecté."
        try:
            return self.server.get_build_console_output(job_name, build_number)
        except Exception as e:
            logger.error(f"Jenkins console error: {e}")
            return ""

    def abort_build(self, job_name: str, build_number: int) -> bool:
        if not self.server:
            return False
        try:
            self.server.stop_build(job_name, build_number)
            return True
        except Exception as e:
            logger.error(f"Jenkins abort error: {e}")
            return False

    def get_last_build_number(self, job_name: str):
        if not self.server:
            return None
        try:
            info = self.server.get_job_info(job_name)
            lb = info.get('lastBuild')
            return lb['number'] if lb else None
        except Exception:
            return None
