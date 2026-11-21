terraform {
  required_version = ">= 1.8.0, < 2.0.0"
  required_providers {
    helm       = { source = "hashicorp/helm", version = "2.17.0" }
    kubernetes = { source = "hashicorp/kubernetes", version = "2.37.1" }
    random     = { source = "hashicorp/random", version = "3.7.2" }
  }
}
data "terraform_remote_state" "aws" {
  backend = "local"
  config  = { path = "${path.module}/../aws/terraform.tfstate" }
}
locals { deployment = data.terraform_remote_state.aws.outputs.deployment }
provider "kubernetes" {
  host                   = local.deployment.cluster_endpoint
  cluster_ca_certificate = base64decode(local.deployment.cluster_ca)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", local.deployment.cluster_name, "--region", local.deployment.region]
  }
}
provider "helm" {
  kubernetes {
    host                   = local.deployment.cluster_endpoint
    cluster_ca_certificate = base64decode(local.deployment.cluster_ca)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.deployment.cluster_name, "--region", local.deployment.region]
    }
  }
}
variable "repo_url" {
  type    = string
  default = "git@github.com:Sthiti04/CC-Project.git"
}
variable "repo_key_file" {
  type    = string
  default = "../../artifacts/gitops_ed25519"
}
variable "branch" {
  type    = string
  default = "main"
}
resource "kubernetes_namespace_v1" "observability" {
  metadata { name = "observability" }
}
resource "random_password" "grafana" {
  length  = 24
  special = false
}
resource "kubernetes_secret_v1" "grafana" {
  metadata {
    name      = "s23-grafana-admin"
    namespace = kubernetes_namespace_v1.observability.metadata[0].name
  }
  data = { admin-user = "admin", admin-password = random_password.grafana.result }
}
resource "helm_release" "argocd" {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.14.0"
  timeout          = 900
  values = [yamlencode({
    dex            = { enabled = false }
    notifications  = { enabled = false }
    applicationSet = { enabled = false }
    server         = { extraArgs = ["--insecure"], service = { type = "ClusterIP" } }
    configs = {
      cm = {
        "resource.customizations.health.argoproj.io_Application" = <<-LUA
          hs = {}
          hs.status = "Progressing"
          hs.message = "Waiting for child application"
          if obj.status ~= nil and obj.status.health ~= nil then
            hs.status = obj.status.health.status
            hs.message = obj.status.health.message or ""
          end
          return hs
        LUA
      }
    }
  })]
}
resource "kubernetes_secret_v1" "repository" {
  metadata {
    name      = "s23-private-github-repository"
    namespace = "argocd"
    labels    = { "argocd.argoproj.io/secret-type" = "repository" }
  }
  data = {
    type          = "git"
    url           = var.repo_url
    sshPrivateKey = file("${path.module}/${var.repo_key_file}")
  }
  depends_on = [helm_release.argocd]
}
resource "helm_release" "root" {
  name      = "s23-root"
  namespace = "argocd"
  chart     = "${path.module}/bootstrap"
  timeout   = 900
  values    = [yamlencode({ repoURL = var.repo_url, branch = var.branch })]
  depends_on = [
    helm_release.argocd, kubernetes_secret_v1.repository, kubernetes_secret_v1.grafana,
  ]
}
