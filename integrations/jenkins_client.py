"""
Jenkins client using requests directly — avoids python-jenkins crumb issues.
"""
import logging
import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings

logger = logging.getLogger(__name__)

JOB_CONFIG_XML = """<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>{description}</description>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition" plugin="workflow-cps">
    <script>{script}</script>
    <sandbox>true</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>"""


class JenkinsClient:
    def __init__(self):
        self.url   = settings.JENKINS_URL.rstrip('/')
        self.auth  = HTTPBasicAuth(settings.JENKINS_USER, settings.JENKINS_TOKEN)
        self._connected = None

    def is_connected(self):
        if self._connected is None:
            try:
                r = requests.get(f"{self.url}/api/json",
                                 auth=self.auth, timeout=5)
                self._connected = r.status_code == 200
            except Exception as e:
                logger.warning(f"Jenkins connection failed: {e}")
                self._connected = False
        return self._connected

    def _get_crumb(self):
        """Get Jenkins crumb for CSRF protection."""
        try:
            r = requests.get(
                f"{self.url}/crumbIssuer/api/json",
                auth=self.auth, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return {data['crumbRequestField']: data['crumb']}
        except Exception:
            pass
        return {}

    def _headers(self):
        h = {'Content-Type': 'application/xml'}
        h.update(self._get_crumb())
        return h

    def job_exists(self, job_name: str) -> bool:
        r = requests.get(
            f"{self.url}/job/{job_name}/api/json",
            auth=self.auth, timeout=5)
        return r.status_code == 200

    def create_or_update_job(self, job_name: str, jenkinsfile: str,
                              description: str = '') -> bool:
        if not self.is_connected():
            logger.warning("Jenkins not connected.")
            return False
        try:
            # Escape XML special chars in jenkinsfile
            safe_script = (jenkinsfile
                           .replace('&', '&amp;')
                           .replace('<', '&lt;')
                           .replace('>', '&gt;'))
            config = JOB_CONFIG_XML.format(
                description=description,
                script=safe_script)

            if self.job_exists(job_name):
                r = requests.post(
                    f"{self.url}/job/{job_name}/config.xml",
                    data=config.encode('utf-8'),
                    auth=self.auth,
                    headers=self._headers(),
                    timeout=10)
                action = "updated"
            else:
                r = requests.post(
                    f"{self.url}/createItem?name={job_name}",
                    data=config.encode('utf-8'),
                    auth=self.auth,
                    headers=self._headers(),
                    timeout=10)
                action = "created"

            if r.status_code in (200, 201):
                logger.info(f"Job '{job_name}' {action} successfully.")
                return True
            else:
                logger.error(f"Jenkins {action} job failed: {r.status_code} {r.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"Jenkins create/update error: {e}")
            return False

    def trigger_build(self, job_name: str) -> dict:
        if not self.is_connected():
            return {'mock': True}
        try:
            r = requests.post(
                f"{self.url}/job/{job_name}/build",
                auth=self.auth,
                headers=self._get_crumb(),
                timeout=10)
            if r.status_code in (200, 201):
                return {'status': 'queued'}
            else:
                raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"Jenkins trigger error: {e}")
            raise

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        try:
            r = requests.get(
                f"{self.url}/job/{job_name}/{build_number}/api/json",
                auth=self.auth, timeout=5)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def get_build_console(self, job_name: str, build_number: int) -> str:
        try:
            r = requests.get(
                f"{self.url}/job/{job_name}/{build_number}/consoleText",
                auth=self.auth, timeout=10)
            return r.text if r.status_code == 200 else ""
        except Exception:
            return ""

    def abort_build(self, job_name: str, build_number: int) -> bool:
        try:
            r = requests.post(
                f"{self.url}/job/{job_name}/{build_number}/stop",
                auth=self.auth,
                headers=self._get_crumb(),
                timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False

    def delete_job(self, job_name: str) -> bool:
        try:
            r = requests.post(
                f"{self.url}/job/{job_name}/doDelete",
                auth=self.auth,
                headers=self._get_crumb(),
                timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False
