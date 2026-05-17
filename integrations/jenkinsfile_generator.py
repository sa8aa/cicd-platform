"""
Generates the Jenkinsfile dynamically from Project fields.
Strategy: DockerHub only, no ECR.
Manifests are injected into the workspace via writeFile (Groovy).
All strings ASCII-only to avoid Jenkins XML parse errors.
"""
from integrations.infra_generator import (
    generate_k8s_deployment,
    generate_k8s_service,
    generate_cloudformation,
)


def _escape_groovy_string(s: str) -> str:
    """Escape a string for use inside a Groovy triple-single-quoted string."""
    return s.replace('\\', '\\\\').replace("'", "\\'")


def generate_jenkinsfile(project) -> str:
    image_name = project.image_name or (
        project.dockerhub_username + '/' + project.jenkins_job_name)
    job_name = project.jenkins_job_name
    region   = project.aws_region
    account  = project.aws_account_id
    key_name = project.aws_key_name
    stack    = project.cf_stack_name
    branch   = project.branch
    repo_url = project.repo_url
    k8s_dep  = project.k8s_deployment_file   # e.g. k8s/deployment.yaml
    k8s_svc  = project.k8s_service_file      # e.g. k8s/service.yaml
    cf_tpl   = project.cf_template_file      # e.g. cloudformation/infra-stack.yaml
    port     = str(project.app_port)

    # Pre-generate manifests if enabled
    if project.generate_manifests:
        cf_content  = _escape_groovy_string(generate_cloudformation(project))
        k8s_dep_content = _escape_groovy_string(generate_k8s_deployment(project))
        k8s_svc_content = _escape_groovy_string(generate_k8s_service(project))
    else:
        cf_content  = None
        k8s_dep_content = None
        k8s_svc_content = None

    jf  = "pipeline {\n"
    jf += "    agent any\n\n"
    jf += "    environment {\n"
    jf += "        DOCKERHUB_CREDENTIALS = credentials('dockerhub-creds')\n"
    jf += "        IMAGE_NAME            = '" + image_name + "'\n"
    jf += "        AWS_REGION            = '" + region + "'\n"
    jf += "        AWS_ACCOUNT_ID        = '" + account + "'\n"
    jf += "        IMAGE_TAG             = \"${BUILD_NUMBER}\"\n"
    jf += "        KEY_NAME              = '" + key_name + "'\n"
    jf += "    }\n\n"
    jf += "    stages {\n\n"

    # Stage 1: Checkout
    jf += "        stage('Checkout') {\n"
    jf += "            steps {\n"
    jf += "                git branch: '" + branch + "',\n"
    jf += "                    url: '" + repo_url + "'\n"
    jf += "            }\n"
    jf += "        }\n\n"

    # Stage 2: Install Dependencies
    jf += "        stage('Install Dependencies') {\n"
    jf += "            steps {\n"
    jf += "                sh '''\n"
    jf += "                    set -e\n"
    jf += "                    python3 -m venv venv\n"
    jf += "                    venv/bin/python -m pip install --upgrade pip --quiet\n"
    jf += "                    venv/bin/python -m pip install -r requirements.txt --quiet\n"
    jf += "                '''\n"
    jf += "            }\n"
    jf += "        }\n\n"

    # Stage 3: Run Tests
    jf += "        stage('Run Tests') {\n"
    jf += "            steps {\n"
    jf += "                sh '''\n"
    jf += "                    set -e\n"
    jf += "                    venv/bin/python manage.py test\n"
    jf += "                '''\n"
    jf += "            }\n"
    jf += "        }\n\n"

    # Stage 4: Build & Push Images
    jf += "        stage('Build & Push Images') {\n"
    jf += "            steps {\n"
    jf += "                sh \"\"\"\n"
    jf += "                    set -e\n"
    jf += "                    docker build -t " + image_name + ":\\${IMAGE_TAG} .\n"
    jf += "                    echo \\$DOCKERHUB_CREDENTIALS_PSW | docker login -u \\$DOCKERHUB_CREDENTIALS_USR --password-stdin\n"
    jf += "                    docker tag " + image_name + ":\\${IMAGE_TAG} " + image_name + ":latest\n"
    jf += "                    docker push " + image_name + ":\\${IMAGE_TAG}\n"
    jf += "                    docker push " + image_name + ":latest\n"
    jf += "                    echo 'Image pushed to DockerHub successfully'\n"
    jf += "                \"\"\"\n"
    jf += "            }\n"
    jf += "            post {\n"
    jf += "                success { echo 'Build and push successful' }\n"
    jf += "                failure { echo 'Build or push failed' }\n"
    jf += "            }\n"
    jf += "        }\n\n"

    # Stage 5: Provision Infra
    jf += "        stage('Provision Infra') {\n"
    jf += "            steps {\n"

    # Inject generated manifests via writeFile if generate_manifests=True
    if cf_content is not None:
        jf += "                // Write generated CloudFormation manifest\n"
        jf += "                sh 'mkdir -p cloudformation k8s'\n"
        jf += "                writeFile file: '" + cf_tpl + "', text: '''" + cf_content + "'''\n"
        jf += "                writeFile file: '" + k8s_dep + "', text: '''" + k8s_dep_content + "'''\n"
        jf += "                writeFile file: '" + k8s_svc + "', text: '''" + k8s_svc_content + "'''\n"

    jf += "                withCredentials([\n"
    jf += "                    usernamePassword(credentialsId: 'aws-credentials',\n"
    jf += "                        usernameVariable: 'AWS_ACCESS_KEY_ID',\n"
    jf += "                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'),\n"
    jf += "                    string(credentialsId: 'aws-session-token',\n"
    jf += "                        variable: 'AWS_SESSION_TOKEN'),\n"
    jf += "                    sshUserPrivateKey(credentialsId: 'ec2-ssh-key',\n"
    jf += "                        keyFileVariable: 'SSH_KEY')\n"
    jf += "                ]) {\n"
    jf += "                    sh \"\"\"\n"
    jf += "                        export AWS_ACCESS_KEY_ID=\\${AWS_ACCESS_KEY_ID}\n"
    jf += "                        export AWS_SECRET_ACCESS_KEY=\\${AWS_SECRET_ACCESS_KEY}\n"
    jf += "                        export AWS_SESSION_TOKEN=\\${AWS_SESSION_TOKEN}\n\n"
    jf += "                        STACK_STATUS=\\$(aws cloudformation describe-stacks \\\n"
    jf += "                            --stack-name " + stack + " \\\n"
    jf += "                            --region " + region + " \\\n"
    jf += "                            --query 'Stacks[0].StackStatus' \\\n"
    jf += "                            --output text 2>/dev/null || echo 'DOES_NOT_EXIST')\n\n"
    jf += "                        echo \"Stack status: \\$STACK_STATUS\"\n\n"
    jf += "                        if [ \"\\$STACK_STATUS\" = \"DOES_NOT_EXIST\" ]; then\n"
    jf += "                            aws cloudformation create-stack \\\n"
    jf += "                                --stack-name " + stack + " \\\n"
    jf += "                                --capabilities CAPABILITY_IAM \\\n"
    jf += "                                --template-body file://" + cf_tpl + " \\\n"
    jf += "                                --parameters \\\n"
    jf += "                                    ParameterKey=ProjectName,ParameterValue=" + job_name + " \\\n"
    jf += "                                    ParameterKey=KeyName,ParameterValue=" + key_name + " \\\n"
    jf += "                                --region " + region + "\n"
    jf += "                            aws cloudformation wait stack-create-complete \\\n"
    jf += "                                --stack-name " + stack + " \\\n"
    jf += "                                --region " + region + "\n"
    jf += "                        elif [ \"\\$STACK_STATUS\" = \"CREATE_COMPLETE\" ] || \\\n"
    jf += "                             [ \"\\$STACK_STATUS\" = \"UPDATE_COMPLETE\" ]; then\n"
    jf += "                            echo 'Stack already exists - skipping'\n"
    jf += "                        else\n"
    jf += "                            echo \"Unexpected stack status: \\$STACK_STATUS\"\n"
    jf += "                            exit 1\n"
    jf += "                        fi\n\n"
    jf += "                        EC2_IP=\\$(aws cloudformation describe-stacks \\\n"
    jf += "                            --stack-name " + stack + " \\\n"
    jf += "                            --query 'Stacks[0].Outputs[?OutputKey==`InstancePublicIP`].OutputValue' \\\n"
    jf += "                            --output text --region " + region + ")\n"
    jf += "                        echo \"EC2 IP: \\$EC2_IP\"\n"
    jf += "                        echo \\$EC2_IP > /tmp/ec2-ip.txt\n"
    jf += "                        chmod 400 \\${SSH_KEY}\n\n"
    jf += "                        for i in \\$(seq 1 30); do\n"
    jf += "                            STATUS=\\$(ssh -i \\${SSH_KEY} -o StrictHostKeyChecking=no \\\n"
    jf += "                                -o ConnectTimeout=10 ec2-user@\\$EC2_IP \\\n"
    jf += "                                \"sudo kubectl get nodes 2>/dev/null | grep Ready || echo NOT_READY\")\n"
    jf += "                            if echo \"\\$STATUS\" | grep -q 'Ready'; then\n"
    jf += "                                echo \"k3s is ready: \\$STATUS\"; break\n"
    jf += "                            fi\n"
    jf += "                            echo \"Attempt \\$i/30 - waiting 10s...\"\n"
    jf += "                            sleep 10\n"
    jf += "                            if [ \\$i -eq 30 ]; then echo 'k3s not ready'; exit 1; fi\n"
    jf += "                        done\n"
    jf += "                        echo \"Infra ready at: \\$EC2_IP\"\n"
    jf += "                    \"\"\"\n"
    jf += "                }\n"
    jf += "            }\n"
    jf += "            post {\n"
    jf += "                success { echo 'Infrastructure provisioned successfully' }\n"
    jf += "                failure { echo 'CloudFormation or k3s setup failed' }\n"
    jf += "            }\n"
    jf += "        }\n\n"

    # Stage 6: Deploy to k3s
    jf += "        stage('Deploy to k3s') {\n"
    jf += "            steps {\n"
    jf += "                withCredentials([\n"
    jf += "                    usernamePassword(credentialsId: 'aws-credentials',\n"
    jf += "                        usernameVariable: 'AWS_ACCESS_KEY_ID',\n"
    jf += "                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'),\n"
    jf += "                    string(credentialsId: 'aws-session-token',\n"
    jf += "                        variable: 'AWS_SESSION_TOKEN'),\n"
    jf += "                    sshUserPrivateKey(credentialsId: 'ec2-ssh-key',\n"
    jf += "                        keyFileVariable: 'SSH_KEY')\n"
    jf += "                ]) {\n"
    jf += "                    sh \"\"\"\n"
    jf += "                        export AWS_ACCESS_KEY_ID=\\${AWS_ACCESS_KEY_ID}\n"
    jf += "                        export AWS_SECRET_ACCESS_KEY=\\${AWS_SECRET_ACCESS_KEY}\n"
    jf += "                        export AWS_SESSION_TOKEN=\\${AWS_SESSION_TOKEN}\n\n"
    jf += "                        EC2_IP=\\$(cat /tmp/ec2-ip.txt)\n\n"
    jf += "                        ssh -i \\${SSH_KEY} -o StrictHostKeyChecking=no ec2-user@\\$EC2_IP \\\n"
    jf += "                            \"sudo kubectl create secret docker-registry dockerhub-secret \\\n"
    jf += "                                --docker-server=https://index.docker.io/v1/ \\\n"
    jf += "                                --docker-username=\\$DOCKERHUB_CREDENTIALS_USR \\\n"
    jf += "                                --docker-password=\\$DOCKERHUB_CREDENTIALS_PSW \\\n"
    jf += "                                --dry-run=client -o yaml | sudo kubectl apply -f -\"\n\n"
    jf += "                        scp -i \\${SSH_KEY} -o StrictHostKeyChecking=no \\\n"
    jf += "                            " + k8s_dep + " " + k8s_svc + " \\\n"
    jf += "                            ec2-user@\\$EC2_IP:/home/ec2-user/\n\n"
    jf += "                        ssh -i \\${SSH_KEY} -o StrictHostKeyChecking=no ec2-user@\\$EC2_IP \\\n"
    jf += "                            \"sudo kubectl apply -f /home/ec2-user/deployment.yaml && \\\n"
    jf += "                             sudo kubectl apply -f /home/ec2-user/service.yaml\"\n\n"
    jf += "                        ssh -i \\${SSH_KEY} -o StrictHostKeyChecking=no ec2-user@\\$EC2_IP \\\n"
    jf += "                            \"sudo kubectl set image deployment/" + job_name + " \\\n"
    jf += "                                " + job_name + "=" + image_name + ":\\${IMAGE_TAG}\"\n\n"
    jf += "                        ssh -i \\${SSH_KEY} -o StrictHostKeyChecking=no ec2-user@\\$EC2_IP \\\n"
    jf += "                            \"sudo kubectl rollout status deployment/" + job_name + " --timeout=180s\"\n\n"
    jf += "                        echo \"App deployed at http://\\$EC2_IP:" + port + "\"\n"
    jf += "                    \"\"\"\n"
    jf += "                }\n"
    jf += "            }\n"
    jf += "            post {\n"
    jf += "                success { echo 'Deployment successful' }\n"
    jf += "                failure { echo 'Deployment failed' }\n"
    jf += "            }\n"
    jf += "        }\n\n"
    jf += "    }\n\n"

    jf += "    post {\n"
    jf += "        always {\n"
    jf += "            sh 'docker logout || true'\n"
    jf += "            cleanWs()\n"
    jf += "        }\n"
    jf += "        success { echo 'Pipeline completed successfully.' }\n"
    jf += "        failure { echo 'Pipeline failed.' }\n"
    jf += "    }\n"
    jf += "}\n"

    return jf
