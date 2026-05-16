"""
Jenkins client using requests directly — avoids python-jenkins crumb issues.
"""
import json
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

_CRED_STORE = "system/domainCredentials/domain/_/credential"


class JenkinsClient:
    def __init__(self):
        self.url  = settings.JENKINS_URL.rstrip('/')
        self.auth = HTTPBasicAuth(settings.JENKINS_USER, settings.JENKINS_TOKEN)
        self._connected = None

    def is_connected(self):
        if self._connected is None:
            try:
                r = requests.get(f"{self.url}/api/json", auth=self.auth, timeout=5)
                self._connected = r.status_code == 200
            except Exception as e:
                logger.warning(f"Jenkins connection failed: {e}")
                self._connected = False
        return self._connected

    def _get_crumb(self):
        try:
            r = requests.get(f"{self.url}/crumbIssuer/api/json", auth=self.auth, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return {data['crumbRequestField']: data['crumb']}
        except Exception:
            pass
        return {}

    def _headers(self, content_type='application/xml'):
        h = {'Content-Type': content_type}
        h.update(self._get_crumb())
        return h

    # ── Job management ────────────────────────────────────────────────────

    def job_exists(self, job_name: str) -> bool:
        r = requests.get(f"{self.url}/job/{job_name}/api/json", auth=self.auth, timeout=5)
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
            config = JOB_CONFIG_XML.format(description=description, script=safe_script)

            if self.job_exists(job_name):
                r = requests.post(
                    f"{self.url}/job/{job_name}/config.xml",
                    data=config.encode('utf-8'), auth=self.auth,
                    headers=self._headers(), timeout=10)
                action = "updated"
            else:
                r = requests.post(
                    f"{self.url}/createItem?name={job_name}",
                    data=config.encode('utf-8'), auth=self.auth,
                    headers=self._headers(), timeout=10)
                action = "created"

            if r.status_code in (200, 201):
                logger.info(f"Job '{job_name}' {action} successfully.")
                return True
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
                auth=self.auth, headers=self._get_crumb(), timeout=10)
            if r.status_code in (200, 201):
                return {'status': 'queued'}
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

    def get_build_console(self, job_name: str, build_number: int,
                          start_byte: int = 0) -> tuple:
        """
        Fetch Jenkins console output progressively.
        Returns (new_text, next_start_byte).
        next_start_byte == 0 means build finished and all output was returned.
        """
        try:
            r = requests.get(
                f"{self.url}/job/{job_name}/{build_number}"
                f"/logText/progressiveText?start={start_byte}",
                auth=self.auth, timeout=10)
            if r.status_code != 200:
                return '', start_byte
            text        = r.text
            next_offset = int(r.headers.get('X-Text-Size', start_byte + len(text.encode())))
            more        = r.headers.get('X-More-Data', 'false').lower() == 'true'
            return text, (next_offset if more else 0)
        except Exception as e:
            logger.debug(f"Jenkins console fetch error: {e}")
            return '', start_byte

    def get_build_stages(self, job_name: str, build_number: int) -> list:
        try:
            r = requests.get(
                f"{self.url}/job/{job_name}/{build_number}/wfapi/describe",
                auth=self.auth, timeout=5)
            if r.status_code == 200:
                return r.json().get('stages', [])
        except Exception as e:
            logger.debug(f"wfapi stages error: {e}")
        return []

    def abort_build(self, job_name: str, build_number: int) -> bool:
        try:
            r = requests.post(
                f"{self.url}/job/{job_name}/{build_number}/stop",
                auth=self.auth, headers=self._get_crumb(), timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False

    def delete_job(self, job_name: str) -> bool:
        try:
            r = requests.post(
                f"{self.url}/job/{job_name}/doDelete",
                auth=self.auth, headers=self._get_crumb(), timeout=5)
            return r.status_code in (200, 302)
        except Exception:
            return False

    # ── Credentials management ────────────────────────────────────────────

    def _credential_exists(self, cred_id: str) -> bool:
        r = requests.get(
            f"{self.url}/credentials/store/system/domain/_/credential/{cred_id}/api/json",
            auth=self.auth, timeout=5)
        return r.status_code == 200

    def _push_credential(self, cred_id: str, xml: str) -> bool:
        """Create or update a credential in Jenkins."""
        if not self.is_connected():
            return False
        try:
            if self._credential_exists(cred_id):
                # Update existing
                r = requests.post(
                    f"{self.url}/credentials/store/system/domain/_/credential/{cred_id}/config.xml",
                    data=xml.encode('utf-8'),
                    auth=self.auth,
                    headers=self._headers(),
                    timeout=10)
                ok = r.status_code in (200, 201)
                logger.info(f"Credential '{cred_id}' updated: {ok}")
            else:
                # Create new
                r = requests.post(
                    f"{self.url}/credentials/store/system/domain/_/createCredentials",
                    data=xml.encode('utf-8'),
                    auth=self.auth,
                    headers=self._headers(),
                    timeout=10)
                ok = r.status_code in (200, 201)
                logger.info(f"Credential '{cred_id}' created: {ok}")
            if not ok:
                logger.error(f"Credential push failed: {r.status_code} {r.text[:300]}")
            return ok
        except Exception as e:
            logger.error(f"Credential push error for '{cred_id}': {e}")
            return False

    def push_dockerhub_credentials(self, username: str, password: str) -> bool:
        """Push dockerhub-creds (Username/Password) to Jenkins."""
        xml = _CRED_USERPASS_XML.format(
            cred_id='dockerhub-creds',
            description='DockerHub credentials — managed by CI/CD Platform',
            username=username,
            password=password,
        )
        return self._push_credential('dockerhub-creds', xml)

    def push_aws_credentials(self, access_key_id: str, secret_access_key: str) -> bool:
        """Push aws-credentials (Username=key_id / Password=secret) to Jenkins."""
        xml = _CRED_USERPASS_XML.format(
            cred_id='aws-credentials',
            description='AWS credentials — managed by CI/CD Platform',
            username=access_key_id,
            password=secret_access_key,
        )
        return self._push_credential('aws-credentials', xml)

    def push_aws_session_token(self, session_token: str) -> bool:
        """Push aws-session-token (Secret Text) to Jenkins."""
        xml = _CRED_SECRET_XML.format(
            cred_id='aws-session-token',
            description='AWS session token — managed by CI/CD Platform',
            secret=session_token,
        )
        return self._push_credential('aws-session-token', xml)

    def push_ssh_key(self, private_key_pem: str) -> bool:
        """Push ec2-ssh-key (SSH private key) to Jenkins."""
        xml = _CRED_SSH_XML.format(
            cred_id='ec2-ssh-key',
            description='EC2 SSH key — managed by CI/CD Platform',
            username='ec2-user',
            private_key=private_key_pem.replace('<', '&lt;').replace('>', '&gt;'),
        )
        return self._push_credential('ec2-ssh-key', xml)

    def push_all_credentials(self, creds: dict) -> dict:
        """
        Push all 4 required credentials in one call.

        creds dict keys:
          dockerhub_username, dockerhub_password,
          aws_access_key_id, aws_secret_access_key,
          aws_session_token (optional),
          ec2_ssh_key (PEM string)

        Returns dict of {cred_id: bool} results.
        """
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
