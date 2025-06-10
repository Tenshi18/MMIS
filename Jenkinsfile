pipeline {
  agent {
    docker {
      image 'ghcr.io/astral-sh/uv:python3.13-bookworm-slim'
      args '--dns=9.9.9.9 --dns=8.8.8.8'
    }
  }
  environment {
    UV_CACHE_DIR = "${env.WORKSPACE}/.uv-cache"
    RSS_CONFIG = credentials('rss_eye_config_json')
  }
  options {
    buildDiscarder(logRotator(numToKeepStr: '10'))
    timestamps()
    timeout(time: 20, unit: 'MINUTES')
  }
  stages {
    stage('Setup venv & Dependencies') {
      steps {
        sh '''
          uv venv .venv
          source .venv/bin/activate
          uv sync --locked --no-dev
        '''
      }
    }
    stage('Build Image') {
      steps {
        sh '''
          . .venv/bin/activate
          uv build -t rss_eye_app .
        '''
      }
    }
    stage('Run Service') {
      steps {
        withCredentials([file(credentialsId: 'rss_eye_config_json', variable: 'RSS_CONFIG')]) {
            sh '. .venv/bin/activate && uv run app/main:app --env RSS_CONFIG="$RSS_CONFIG"'
        }
      }
    }
  }
}
