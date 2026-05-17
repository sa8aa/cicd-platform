"""
Creates Jenkins credentials automatically from Project fields.
The user fills credentials in Django form → Django pushes them to Jenkins.
"""
import json
import logging
import requests
from requests.auth import HTTPBasicAuth
from django.conf import settings

logger = logging.getLogger(__name__)


class JenkinsCredentialsManager:
    """
    Manages Jenkins credentials via the Jenkins Credentials API.
    Creates/updates credentials so the Jenkinsfile can reference them by ID.
    """

    def __init__(self):
        self.url  = settings.JENKINS_URL.rstrip('/')
        self.auth = HTTPBasicAuth(settings.JENKINS_USER, settings.JENKINS_TOKEN)

    def _get_crumb(self):
        try:
            r = requests.get(f"{self.url}/crumbIssuer/api/json",
                             auth=self.auth, timeout=5)
            if r.status_code == 200:
                d = r.json()
                return {d['crumbRequestField']: d['crumb']}
        except Exception:
            pass
        return {}

    def _post(self, url, data):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        headers.update(self._get_crumb())
        return requests.post(url, data=data, auth=self.auth,
                             headers=headers, timeout=10)

    def _create_username_password(self, cred_id, username, password, description=''):
        """Creates a Username/Password credential in Jenkins."""
        payload = {
            'json': json.dumps({
                "": "0",
                "credentials": {
                    "scope": "GLOBAL",
                    "id": cred_id,
                    "description": description,
                    "username": username,
                    "password": password,
                    "$class": "com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl"
                }
            })
        }
        url = (f"{self.url}/credentials/store/system/domain/_/"
               f"createCredentials")
        r = self._post(url, payload)
        if r.status_code in (200, 201, 302):
            logger.info(f"Credential '{cred_id}' created/updated.")
            return True
        # Try update if exists
        return self._update_username_password(cred_id, username, password, description)

    def _update_username_password(self, cred_id, username, password, description=''):
        payload = {
            'json': json.dumps({
                "": "0",
                "credentials": {
                    "scope": "GLOBAL",
                    "id": cred_id,
                    "description": description,
                    "username": username,
                    "password": password,
                    "$class": "com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl"
                }
            })
        }
        url = (f"{self.url}/credentials/store/system/domain/_/"
               f"credential/{cred_id}/updateSubmit")
        r = self._post(url, payload)
        return r.status_code in (200, 201, 302)

    def _create_secret_text(self, cred_id, secret, description=''):
        """Creates a Secret Text credential in Jenkins."""
        payload = {
            'json': json.dumps({
                "": "0",
                "credentials": {
                    "scope": "GLOBAL",
                    "id": cred_id,
                    "description": description,
                    "secret": secret,
                    "$class": "org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl"
                }
            })
        }
        url = (f"{self.url}/credentials/store/system/domain/_/"
               f"createCredentials")
        r = self._post(url, payload)
        if r.status_code in (200, 201, 302):
            logger.info(f"Secret '{cred_id}' created.")
            return True
        return self._update_secret_text(cred_id, secret, description)

    def _update_secret_text(self, cred_id, secret, description=''):
        payload = {
            'json': json.dumps({
                "": "0",
                "credentials": {
                    "scope": "GLOBAL",
                    "id": cred_id,
                    "description": description,
                    "secret": secret,
                    "$class": "org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl"
                }
            })
        }
        url = (f"{self.url}/credentials/store/system/domain/_/"
               f"credential/{cred_id}/updateSubmit")
        r = self._post(url, payload)
        return r.status_code in (200, 201, 302)

    def _create_ssh_key(self, cred_id, private_key, description=''):
        """Creates an SSH Private Key credential in Jenkins."""
        payload = {
            'json': json.dumps({
                "": "0",
                "credentials": {
                    "scope": "GLOBAL",
                    "id": cred_id,
                    "description": description,
                    "username": "ec2-user",
                    "privateKeySource": {
                        "stapler-class": "com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey$DirectEntryPrivateKeySource",
                        "privateKey": private_key
                    },
                    "$class": "com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey"
                }
            })
        }
        url = (f"{self.url}/credentials/store/system/domain/_/"
               f"createCredentials")
        r = self._post(url, payload)
        if r.status_code in (200, 201, 302):
            logger.info(f"SSH key '{cred_id}' created.")
            return True
        # Try update
        url2 = (f"{self.url}/credentials/store/system/domain/_/"
                f"credential/{cred_id}/updateSubmit")
        r2 = self._post(url2, payload)
        return r2.status_code in (200, 201, 302)

    def push_all_credentials(self, project) -> dict:
        """
        Push all credentials from a Project to Jenkins.
        Returns dict with success/fail for each credential.
        """
        results = {}

        # 1. DockerHub credentials
        if project.dockerhub_username and project.dockerhub_token:
            results['dockerhub'] = self._create_username_password(
                cred_id=project.cred_id_dockerhub,
                username=project.dockerhub_username,
                password=project.dockerhub_token,
                description=f"DockerHub credentials for {project.name}")

        # 2. AWS Access Key + Secret Key
        if project.aws_access_key_id and project.aws_secret_access_key:
            results['aws_credentials'] = self._create_username_password(
                cred_id=project.cred_id_aws,
                username=project.aws_access_key_id,
                password=project.aws_secret_access_key,
                description=f"AWS credentials for {project.name}")

        # 3. AWS Session Token
        if project.aws_session_token:
            results['aws_session_token'] = self._create_secret_text(
                cred_id=project.cred_id_aws_token,
                secret=project.aws_session_token,
                description=f"AWS Session Token for {project.name}")

        # 4. EC2 SSH Private Key (.pem)
        if project.ec2_private_key:
            results['ec2_ssh_key'] = self._create_ssh_key(
                cred_id=project.cred_id_ssh,
                private_key=project.ec2_private_key,
                description=f"EC2 SSH Key for {project.name}")

        logger.info(f"Credentials pushed for {project.name}: {results}")
        return results
