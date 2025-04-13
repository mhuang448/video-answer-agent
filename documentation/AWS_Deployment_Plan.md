# AWS Deployment Guide: Video Answer Agent (ECR + App Runner)

This document provides a step-by-step guide for deploying the `video-answer-agent` backend services (`video-agent-backend` and `perplexity-mcp-server`) to AWS using Elastic Container Registry (ECR) and AWS App Runner. This approach prioritizes deployment speed and simplicity.

**Target Audience:** Junior developers with minimal AWS experience.

**Deployment Strategy:**

- **Container Registry:** AWS ECR (Elastic Container Registry) - Stores our built Docker images privately.
- **Compute Service:** AWS App Runner - Runs our containers based on the images in ECR, managing scaling, networking, and deployments with minimal configuration.
- **Secrets Management:** AWS Systems Manager Parameter Store (Standard Tier) - Securely stores API keys and other sensitive configurations.

---

## Phase 1: Prerequisites & Initial Setup

1.  **AWS Account:** Ensure you have an AWS account with sufficient permissions to create/manage IAM users/roles/policies, ECR repositories, SSM Parameter Store parameters, and App Runner services.
2.  **AWS CLI:** Install and configure the AWS Command Line Interface (CLI) on your local machine (MacBook).
    - **Install:** Follow instructions at [Installing or updating the latest version of the AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
    - **Configure IAM User for CLI:**
      - Go to the AWS IAM console. Create a new IAM user (e.g., `cli-deployer`). **Do not** grant console access.
      - Attach necessary permissions policies directly. Start with `AmazonEC2ContainerRegistryFullAccess` (or `PowerUser`) and `IAMReadOnlyAccess` (useful for checking roles/policies via CLI). More permissions might be needed later depending on actions taken via CLI.
      - Navigate to the created user -> Security credentials -> Create access key. Select "Command Line Interface (CLI)" as the use case.
      - **Securely save the generated Access Key ID and Secret Access Key.** This is the only time the secret key is shown.
    - **Configure Local CLI:** Open your terminal and run `aws configure`. Enter the saved Access Key ID, Secret Access Key, your default AWS Region (e.g., `us-east-2`, matching where you'll create resources), and default output format (e.g., `json`).
    - **Verify:** Run `aws sts get-caller-identity` in your terminal. It should return the details of the IAM user you configured, confirming the CLI can communicate with AWS.
3.  **Docker:** Ensure Docker Desktop is installed and running on your local machine.
4.  **Project Code:** Have the `video-answer-agent` project code available locally.

---

## Phase 2: Secure Secrets with SSM Parameter Store

We will store sensitive API keys and configuration securely using the **free Standard tier** of AWS Systems Manager Parameter Store.

1.  **Navigate to Parameter Store:** Go to AWS Console -> Systems Manager -> Parameter Store (under Application Management).
2.  **Create Parameters:** For _each_ secret required by the services, click "Create parameter":
    - **Secrets (Use `SecureString` Type):**
      - **Name:** Use a hierarchical name like `/video-answer-agent/SECRET_NAME` (e.g., `/video-answer-agent/PERPLEXITY_API_KEY`).
      - **Tier:** **Standard**
      - **Type:** **SecureString**
      - **KMS key source:** Keep default **"My current account"** (uses the free AWS-managed KMS key for SSM).
      - **Value:** Paste the actual secret value.
      - **Create for:** `PERPLEXITY_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `PINECONE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
    - **Configuration (Use `String` Type):**
      - **Name:** `/video-answer-agent/CONFIG_NAME` (e.g., `/video-answer-agent/AWS_REGION`).
      - **Tier:** **Standard**
      - **Type:** **String**
      - **Value:** Paste the configuration value.
      - **Create for:** `AWS_REGION`, `S3_BUCKET_NAME`, `PINECONE_INDEX_HOST`, `PINECONE_INDEX_NAME`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_SYNTHESIS_MODEL`, `ANTHROPIC_TOOL_SELECTION_MODEL`.
3.  **Copy ARNs:** After creating each parameter, view its details and **copy its ARN**. You will need these ARNs later for IAM policies and App Runner configuration. ARNs look like `arn:aws:ssm:REGION:ACCOUNT_ID:parameter/your/parameter/name`.

---

## Phase 3: Build & Push Docker Images to ECR

1.  **Create ECR Repositories:**

    - Go to AWS Console -> Elastic Container Registry (ECR).
    - Create two **private** repositories:
      - `perplexity-mcp-server`
      - `video-agent-backend`
    - For each repository:
      - Keep **Image tag mutability:** `Mutable` (simplifies using the `:latest` tag for the demo).
      - Keep **Encryption configuration:** `AES-256` (default, secure, no extra cost).
    - Note the **URI** for each repository (e.g., `ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/repository-name`).

2.  **Log in Docker to ECR:**

    - Open your local terminal.
    - Run the ECR login command (replace `REGION` and `ACCOUNT_ID`):
      ```bash
      aws ecr get-login-password --region REGION | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com
      ```
    - You should see "Login Succeeded".

3.  **Prepare `.dockerignore` Files:**

    - Ensure `backend/.dockerignore` contains:
      ```
      technical-pipeline-scripts/
      .venv/
      __pycache__/
      *.pyc
      *.env
      ```
    - Ensure `backend/perplexity-mcp-server/.dockerignore` contains:
      ```
      node_modules/
      dist/
      *.env
      ```
    - **Why:** This prevents unnecessary or sensitive local files from being included in the Docker build context, resulting in smaller, cleaner, and more secure images.

4.  **Build Docker Images:**

    - Run these commands from the **root directory** of your project:

      ```bash
      # Build mcp-server image
      docker build -t perplexity-mcp-server:latest -f backend/perplexity-mcp-server/Dockerfile ./backend/perplexity-mcp-server

      # Build backend image
      docker build -t video-answer-agent-backend:latest -f backend/Dockerfile ./backend
      ```

    - **Explanation:**
      - `docker build`: Builds an image.
      - `-t name:tag`: Assigns a local name and tag (e.g., `latest`) to the built image.
      - `-f path/to/Dockerfile`: Specifies which Dockerfile to use.
      - `./path/to/context`: Specifies the directory containing the source code and the relevant `.dockerignore` file.

5.  **Tag Images for ECR:**

    - Create an additional tag for each image that includes the ECR repository URI. Replace `YOUR_..._URI` with the actual URIs from Step 1.

      ```bash
      # Tag mcp-server image for ECR
      docker tag perplexity-mcp-server:latest YOUR_MCP_SERVER_ECR_REPO_URI:latest

      # Tag backend image for ECR
      docker tag video-answer-agent-backend:latest YOUR_BACKEND_ECR_REPO_URI:latest
      ```

    - **Why:** The `docker push` command needs the full ECR URI in the tag to know where to send the image.

6.  **Push Images to ECR:**

    - Upload the tagged images to your ECR repositories:

      ```bash
      # Push mcp-server image
      docker push YOUR_MCP_SERVER_ECR_REPO_URI:latest

      # Push backend image
      docker push YOUR_BACKEND_ECR_REPO_URI:latest
      ```

    - **Note:** You will likely see "Layer already exists" for many layers on subsequent pushes – this is normal and efficient, as Docker only uploads changed layers.

---

## Phase 4: Configure IAM Roles & Policies for App Runner

App Runner needs permissions to run your application, pull images, and access secrets. We'll create IAM Roles and Policies for this.

1.  **Create IAM Policy for SSM Access:**

    - Go to AWS Console -> IAM -> Policies -> Create policy.
    - Select the **JSON** tab.
    - Paste the following JSON, **replacing ALL placeholders** (`YOUR_REGION`, `YOUR_ACCOUNT_ID`, `/YOUR/PARAMETER/NAME`) with your actual values. **Include the ARNs for ALL parameters needed by BOTH services if using a single policy, OR create separate policies.**
      ```json
      {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": [
              "ssm:GetParameters" // Allows retrieving parameters
            ],
            "Resource": [
              "arn:aws:ssm:YOUR_REGION:YOUR_ACCOUNT_ID:parameter/video-answer-agent/PERPLEXITY_API_KEY",
              "arn:aws:ssm:YOUR_REGION:YOUR_ACCOUNT_ID:parameter/video-answer-agent/AWS_ACCESS_KEY_ID",
              "arn:aws:ssm:YOUR_REGION:YOUR_ACCOUNT_ID:parameter/video-answer-agent/AWS_SECRET_ACCESS_KEY",
              "arn:aws:ssm:YOUR_REGION:YOUR_ACCOUNT_ID:parameter/video-answer-agent/PINECONE_API_KEY"
              // ... Add ALL other needed parameter ARNs here ...
            ]
          }
          // Optional: Add a separate statement for KMS Decrypt if needed,
          // but often implicitly allowed for SSM SecureStrings using default keys.
        ]
      }
      ```
    - Click through Tags and Review.
    - Give the policy a descriptive **Name** (e.g., `AppRunner-VideoAgent-SSM-Access-Policy`).
    - Click **Create policy**.

2.  **Create IAM Instance Role(s):**
    - You will need an **Instance Role** for _each_ App Runner service (`mcp-server` and `backend`).
    - Go to AWS Console -> IAM -> Roles -> Create role.
    - **Trusted entity type:** Select **"Custom trust policy"**.
    - **Paste this JSON** to allow App Runner tasks to assume the role:
      ```json
      {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Principal": {
              "Service": "tasks.apprunner.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
          }
        ]
      }
      ```
    - Click **Next**.
    - **Add permissions:** Search for and select the **SSM access policy** you created in Step 1.
    - **For the `backend` role ONLY:** You also need S3 permissions. Search for and select the AWS managed policy `AmazonS3FullAccess` (for simplicity in the demo) or create a more specific policy granting `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` only for your specific `S3_BUCKET_NAME`.
    - Click **Next**.
    - **Role name:** Give it a specific name (e.g., `AppRunner-MCP-Server-InstanceRole` or `AppRunner-Backend-InstanceRole`).
    - Click **Create role**. Repeat this process to create the second role if you created separate SSM policies.

---

## Phase 5: Deploy Services with AWS App Runner

1.  **Deploy `mcp-server` Service:**

    - Go to AWS Console -> AWS App Runner -> Create service.
    - **Source:** Container registry, Amazon ECR. Browse and select the `perplexity-mcp-server` repository and `:latest` tag.
    - **Deployment settings:** Manual trigger.
    - **ECR access role:** Choose **"Create new service role"** (App Runner manages ECR pull permissions).
    - Click **Next**.
    - **Configure service:**
      - **Service name:** `perplexity-mcp-server-prod` (or similar).
      - **Virtual CPU/memory:** Start small (e.g., 1 vCPU, 2 GB).
      - **Port:** `8080`.
      - **Environment variables:** Add `PERPLEXITY_API_KEY`, choose "Reference value from...", and paste the **ARN** of the corresponding SSM parameter.
      - **Instance role:** Select the **Instance Role** you created for the MCP server (e.g., `AppRunner-MCP-Server-InstanceRole`).
      - **Health check:** Defaults are usually fine.
      - **Networking/Security:** Keep defaults (Public access, AWS-owned KMS key).
    - Click **Next**.
    - Review and click **"Create & deploy"**.
    - **Wait:** Wait for the status to become **"Running"**.
    - **Copy URL:** Note down the **Default domain** HTTPS URL (e.g., `https://xyz.region.awsapprunner.com`). You need this for the backend. Append your SSE path: `https://xyz.region.awsapprunner.com/sse`.

2.  **Deploy `backend` Service:**
    - Go back to App Runner -> Create service.
    - **Source:** Container registry, Amazon ECR. Browse and select the `video-agent-backend` repository and `:latest` tag.
    - **Deployment settings:** Manual trigger.
    - **ECR access role:** Choose **"Create new service role"**.
    - Click **Next**.
    - **Configure service:**
      - **Service name:** `video-agent-backend-prod` (or similar).
      - **Virtual CPU/memory:** Start reasonably (e.g., 1 vCPU, 2 GB).
      - **Port:** `8000`.
      - **Environment variables:**
        - Add `MCP_PERPLEXITY_SSE_URL`: Paste the **full HTTPS URL** of the deployed `mcp-server` (including `/sse`) directly as the **Value** (plain text).
        - Add ALL other required env vars (`AWS_ACCESS_KEY_ID`, `PINECONE_API_KEY`, `S3_BUCKET_NAME`, etc.): For each, choose "Reference value from..." and paste the **ARN** of the corresponding SSM parameter.
      - **Instance role:** Select the **Instance Role** you created for the backend service (e.g., `AppRunner-Backend-InstanceRole`).
      - **Health check:** Defaults are usually fine (path `/` should work for FastAPI).
      - **Networking/Security:** Keep defaults.
    - Click **Next**.
    - Review and click **"Create & deploy"**.
    - **Wait:** Wait for the status to become **"Running"**.

---

## Phase 6: Verification

1.  **Check Status:** Ensure both App Runner services show status "Running".
2.  **Check Logs:** Examine application logs under the "Logs" tab for each service if issues occur. Look for errors related to environment variables, secret retrieval, or connections.
3.  **Test Backend:** Access the **Default domain** URL of the `video-agent-backend-prod` service in your browser. You should see the root FastAPI response.
4.  **Test API:** Use `curl`, Postman, or your deployed frontend (once configured) to hit API endpoints on the `backend` service URL (e.g., `/api/query/async`) to test the end-to-end flow.

---

## Phase 7: Future Updates

1.  Make code changes locally.
2.  Rebuild the relevant Docker image (`docker build ...`).
3.  Tag the new image for ECR (`docker tag ...`).
4.  Push the new image to ECR (`docker push ...`).
5.  Go to the corresponding App Runner service in the AWS Console.
6.  Click **"Deploy"** to trigger App Runner to pull the latest image and update the service.
