# Using AWS Bedrock

SWE-smith uses [litellm](https://docs.litellm.ai/) for LLM calls, which supports AWS Bedrock as a provider. This is useful when you don't have direct API keys for Anthropic or OpenAI but have access to these models through AWS.

## Prerequisites

1. **AWS CLI v2** installed and configured ([install guide](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html))
2. **boto3** installed in your Python environment: `pip install boto3`
3. Valid AWS credentials with Bedrock model access

## AWS Authentication

Set your default region:

```bash
export AWS_DEFAULT_REGION=us-east-1
```

Authenticate using `aws sso login` or `aws configure`:

```bash
# Option 1: SSO login (recommended for organizations)
aws sso login

# Option 2: Configure access keys directly
aws configure
```

See the [AWS CLI authentication docs](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-authentication.html) for more options.

## Model Strings

Bedrock models use the `bedrock/` prefix in litellm. Common model IDs:

| Model | litellm string |
|-------|---------------|
| Claude Sonnet 4 | `bedrock/us.anthropic.claude-sonnet-4-20250514` |
| Claude Sonnet 4.6 | `bedrock/us.anthropic.claude-sonnet-4-6` |
| Claude Haiku 3.5 | `bedrock/us.anthropic.claude-3-5-haiku-20241022` |

The `us.` prefix routes to a US cross-region inference profile. Check the [AWS Bedrock docs](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html) for available model IDs in your region.

## Usage with SWE-smith

### Bug Generation

Override the model on the command line:

```bash
python -m swesmith.bug_gen.llm.modify Instagram__MonkeyType.70c3acf6 \
    --config_file configs/bug_gen/lm_modify.yml \
    --model bedrock/us.anthropic.claude-sonnet-4-6 \
    --n_bugs 1
```

### Issue Generation

The issue generation script reads the model from the config file. A Bedrock-specific config is provided at `configs/issue_gen/ig_v2_bedrock.yaml`:

```bash
python -m swesmith.issue_gen.generate \
    -d logs/task_insts/<repo>.json \
    -c configs/issue_gen/ig_v2_bedrock.yaml \
    -w 1
```

To create your own, copy any config and change the `model` field:

```yaml
model: bedrock/us.anthropic.claude-sonnet-4-6
```

## Troubleshooting

- **`NoCredentialError`**: Run `aws sso login` or `aws configure` to refresh credentials.
- **`AccessDeniedException`**: Verify your IAM role has `bedrock:InvokeModel` permission for the requested model, and that you have requested model access in the Bedrock console.
- **`ValidationException` with model ID**: Check that the model ID is correct and available in your region. Model availability varies by region.
