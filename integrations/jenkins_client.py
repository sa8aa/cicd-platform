"""
Jenkins client using requests.Session — persistent session fixes crumb issues.
"""
import json
import time
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

# ── Credential XML templates ───────────────────────────────────────────────

_CRED_USERPASS_XML = """<com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl>
  <scope>GLOBAL</scope>
  <id>{cred_id}</id>
  <description>{description}</description>
  <username>{username}</username>
  <password>{password}</password>
</com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl>"""

_CRED_SECRET_XML = """<org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl>
  <scope>GLOBAL</scope>
  <id>{cred_id}</id>
  <description>{description}</description>
  <secret>{secret}</secret>
</org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl>"""

_CRED_SSH_XML = """<com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey>
  <scope>GLOBAL</scope>
  <id>{cred_id}</id>
  <description>{description}</description>
  <username>{username}</username>
  <privateKeySource class="com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey$DirectEntryPrivateKeySource">
    <privateKey>{private_key}</privateKey>
  </privateKeySource>
</com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey>"""


class JenkinsClient:
    def __init__(self):
        self.url = settings.JENKINS_URL.rstrip('/')
        # Persistent session — crumb and cookies stay consistent across calls
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(settings.JENKINS_USER, settings.JENKINS_TOKEN)
        self._connected = None
        self._crumb_cache = None

    def is_connected(self):
        if self._connected is None:
            try:
                r = self.session.get(f"{self.url}/api/json", timeout=5)
                self._connected = r.status_code == 200
            except Exception as e:
                logger.warning(f"Jenkins connection failed: {e}")
                self._connected = False
        return self._connected

    def _get_crumb(self):
        """Fetch crumb once per session and cache it."""
        if self._crumb_cache:
            return self._crumb_cache
        try:
            r = self.session.get(f"{self.url}/crumbIssuer/api/json", timeout=5)
            if r.status_code == 200:
                data = r.json()
                self._crumb_cache = {data['crumbRequestField']: data['crumb']}
                return self._crumb_cache
        except Exception as e:
            logger.warning(f"Crumb fetch failed: {e}")
        return {}

    def _headers(self, content_type='application/xml'):
        h = {'Content-Type': content_type}
        h.update(self._get_crumb())
        return h

    # ── Job management ────────────────────────────────────────────────────

    def job_exists(self, job_name: str) -> bool:
        r = self.session.get(
            f"{self.url}/job/{job_name}/api/json", timeout=5)
        return r.status_code == 200

    def create_or_update_job(self, job_name: str, jenkinsfile: str,
                              description: str = '') -> bool:
        if not self.is_connected():
            logger.warning("Jenkins not connected.")
            return False
        try:
            safe_script = (jenkinsfile
                           .replace('&', '&amp;')
                           .replace('<', '&lt;')
                           .replace('>', '&gt;'))
            config = JOB_CONFIG_XML.format(
                description=description or '',
                script=safe_script,
            )
            headers = self._headers()

            if self.job_exists(job_name):
                r = self.session.post(
                    f"{self.url}/job/{job_name}/config.xml",
                    data=config.encode('utf-8'),
                    headers=headers,
                    timeout=15,
                )
                action = "updated"
            else:
                r = self.session.post(
                    f"{self.url}/createItem?name={job_name}",
                    data=config.encode('utf-8'),
                    headers=headers,
                    timeout=15,
                )
                action = "created"

            if r.status_code in (200, 201):
                logger.info(f"Job '{job_name}' {action} successfully.")
                return True

            logger.error(
                f"Jenkins {action} job failed: {r.status_code} {r.text[:300]}")
            return False

        except Exception as e:
            logger.error(f"Jenkins create/update error: {e}")
            return False

    def trigger_build(self, job_name: str) -> dict:
        """
        Triggers a build and resolves the build number from the Jenkins queue.
        Returns {'build_number': int, 'build_url': str} or {'mock': True}.
        """
        if not self.is_connected():
            return {'mock': True}
        try:
            r = self.session.post(
                f"{self.url}/job/{job_name}/build",
                headers=self._get_crumb(),
                timeout=10,
            )
            if r.status_code not in (200, 201):
                raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")

            queue_url = r.headers.get('Location', '')
            if not queue_url:
                raise Exception("No Location header in Jenkins response")

            queue_api = queue_url.rstrip('/') + '/api/json'

            # Poll until Jenkins assigns a build number (usually 1-5s)
            for attempt in range(20):
                time.sleep(2)
                try:
                    qr = self.session.get(queue_api, timeout=5)
                    if qr.status_code == 200:
                        data = qr.json()
                        executable = data.get('executable')
                        if executable:
                            build_number = executable.get('number')
                            build_url    = executable.get('url', '')
                            logger.info(
                                f"Build #{build_number} started for '{job_name}'")
                            return {
                                'build_number': build_number,
                                'build_url':    build_url,
                                'status':       'queued',
                            }
                except Exception as e:
                    logger.debug(f"Queue poll attempt {attempt}: {e}")

            raise Exception(
                "Timed out waiting for Jenkins to assign a build number")

        except Exception as e:
            logger.error(f"Jenkins trigger error: {e}")
            raise

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        try:
            r = self.session.get(
                f"{self.url}/job/{job_name}/{build_number}/api/json",
                timeout=5)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def get_build_console(self, job_name: str, build_number: int,
                          start_byte: int = 0) -> tuple:
        try:
            r = self.session.get(
                f"{self.url}/job/{job_name}/{build_number}"
                f"/logText/progressiveText?start={start_byte}",
                timeout=10)
            if r.status_code != 200:
                return '', start_byte
            text        = r.text
            next_offset = int(r.headers.get('X-Text-Size',
                                            start_byte + len(text.encode())))
            more        = r.headers.get('X-More-Data', 'false').lower() == 'true'
            return text, (next_offset if more else 0)
        except Exception as e:
            logger.debug(f"Jenkins console fetch error: {e}")
            return '', start_byte

    def get_build_stages(self, job_name: str, build_number: int) -> list:
        try:
            r = self.session.get(
                f"{self.url}/job/{job_name}/{build_number}/wfapi/describe",
                timeout=5)
            if r.status_code == 200:
                return r.json().get('stages', [])
        except Exception as e:
            logger.debug(f"wfapi stages error: {e}")
        return []

    def abort_build(self, job_name: str, build_number: int) -> bool:
        try:
            r = self.session.post(
                f"{self.url}/job/{job_name}/{build_number}/stop",
                headers=self._get_crumb(),
                timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False

    def delete_job(self, job_name: str) -> bool:
        try:
            r = self.session.post(
                f"{self.url}/job/{job_name}/doDelete",
                headers=self._get_crumb(),
                timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False

    # ── Credentials management ────────────────────────────────────────────

    def _credential_exists(self, cred_id: str) -> bool:
        r = self.session.get(
            f"{self.url}/credentials/store/system/domain/_/"
            f"credential/{cred_id}/api/json",
            timeout=5)
        return r.status_code == 200

    def _push_credential(self, cred_id: str, xml: str) -> bool:
        if not self.is_connected():
            return False
        try:
            headers = self._headers()
            if self._credential_exists(cred_id):
                r = self.session.post(
                    f"{self.url}/credentials/store/system/domain/_/"
                    f"credential/{cred_id}/config.xml",
                    data=xml.encode('utf-8'),
                    headers=headers,
                    timeout=10)
            else:
                r = self.session.post(
                    f"{self.url}/credentials/store/system/domain/_/"
                    f"createCredentials",
                    data=xml.encode('utf-8'),
                    headers=headers,
                    timeout=10)

            ok = r.status_code in (200, 201)
            if not ok:
                logger.error(
                    f"Credential '{cred_id}' push failed: "
                    f"{r.status_code} {r.text[:300]}")
            return ok
        except Exception as e:
            logger.error(f"Credential push error for '{cred_id}': {e}")
            return False

    def push_dockerhub_credentials(self, username: str, password: str) -> bool:
        xml = _CRED_USERPASS_XML.format(
            cred_id='dockerhub-creds',
            description='DockerHub credentials — managed by CI/CD Platform',
            username=username,
            password=password,
        )
        return self._push_credential('dockerhub-creds', xml)

    def push_aws_credentials(self, access_key_id: str,
                              secret_access_key: str) -> bool:
        xml = _CRED_USERPASS_XML.format(
            cred_id='aws-credentials',
            description='AWS credentials — managed by CI/CD Platform',
            username=access_key_id,
            password=secret_access_key,
        )
        return self._push_credential('aws-credentials', xml)

    def push_aws_session_token(self, session_token: str) -> bool:
        xml = _CRED_SECRET_XML.format(
            cred_id='aws-session-token',
            description='AWS session token — managed by CI/CD Platform',
            secret=session_token,
        )
        return self._push_credential('aws-session-token', xml)

    def push_ssh_key(self, private_key_pem: str) -> bool:
        xml = _CRED_SSH_XML.format(
            cred_id='ec2-ssh-key',
            description='EC2 SSH key — managed by CI/CD Platform',
            username='ec2-user',
            private_key=private_key_pem.replace(
                '<', '&lt;').replace('>', '&gt;'),
        )
        return self._push_credential('ec2-ssh-key', xml)

    def push_all_credentials(self, creds: dict) -> dict:
        results = {}
        if creds.get('dockerhub_username') and creds.get('dockerhub_password'):
            results['dockerhub-creds'] = self.push_dockerhub_credentials(
                creds['dockerhub_username'], creds['dockerhub_password'])
        if creds.get('aws_access_key_id') and creds.get('aws_secret_access_key'):
            results['aws-credentials'] = self.push_aws_credentials(
                creds['aws_access_key_id'], creds['aws_secret_access_key'])
        if creds.get('aws_session_token'):
            results['aws-session-token'] = self.push_aws_session_token(
                creds['aws_session_token'])
        if creds.get('ec2_ssh_key'):
            results['ec2-ssh-key'] = self.push_ssh_key(creds['ec2_ssh_key'])
        return results
