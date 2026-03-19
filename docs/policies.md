# Policies

Policies let you control what agents can and cannot do with registered CLI
tools. Every policy has two layers:

| Layer | Enforcement | Purpose |
|-------|-------------|---------|
| **Deterministic rules** | Automatic — blocked before execution | Hard guardrails: specific commands, flags, or argument patterns |
| **Abstract rules** | Advisory — surfaced in output | Soft guidelines: natural-language intent the agent should respect |

## Rule types

### `deny_command`

Blocks a command or subcommand path. Paths are dot-separated and
prefix-matched, so denying `"remote"` also blocks `"remote.add"`,
`"remote.remove"`, etc.

```
{"kind": "deny_command", "target": "delete", "description": "No deletions allowed"}
```

### `deny_flag`

Blocks a specific flag. Matches the exact flag name and `--flag=value` forms.
Denying `"--force"` does **not** block `"--force-with-lease"` — the match is
exact up to the `=` separator.

```
{"kind": "deny_flag", "target": "--force", "description": "Force operations are prohibited"}
```

### `deny_pattern`

Blocks any argument matching a Python regular expression. The pattern is
evaluated with `re.search()`, so partial matches trigger the rule. Use
anchors (`^`, `$`) for exact matches.

```
{"kind": "deny_pattern", "target": "^production$", "description": "Cannot target production"}
```

### Abstract rules

Free-form natural language. Not enforced programmatically — the agent
receives these as advisory messages alongside command output and
inspection results.

```
"Only use read-only commands unless the user explicitly asks for changes."
```

---

## Real-world examples

The examples below show how to register popular CLI tools and set up
policies that make sense for common scenarios. Each example includes the
`set_policy` call exactly as an agent or operator would issue it.

---

### Kubernetes (`kubectl`)

`kubectl` is the command-line tool for interacting with Kubernetes
clusters. It can list pods, deploy applications, scale workloads, and
delete entire namespaces — so controlling what an agent can do with it
is critical.

#### Read-only cluster access

Allow the agent to inspect cluster state but prevent any mutations:

```
register_cli("kubectl", max_depth=2)

set_policy("kubectl",
    deterministic_rules=[
        {"kind": "deny_command", "target": "delete",
         "description": "Deleting resources is not allowed"},
        {"kind": "deny_command", "target": "apply",
         "description": "Applying manifests could change cluster state"},
        {"kind": "deny_command", "target": "create",
         "description": "Creating resources is not allowed"},
        {"kind": "deny_command", "target": "patch",
         "description": "Patching resources is not allowed"},
        {"kind": "deny_command", "target": "replace",
         "description": "Replacing resources is not allowed"},
        {"kind": "deny_command", "target": "edit",
         "description": "Editing resources is not allowed"},
        {"kind": "deny_command", "target": "scale",
         "description": "Scaling workloads is not allowed"},
        {"kind": "deny_command", "target": "rollout",
         "description": "Rollout changes are not allowed"},
        {"kind": "deny_command", "target": "drain",
         "description": "Draining nodes is not allowed"},
        {"kind": "deny_command", "target": "cordon",
         "description": "Cordoning nodes is not allowed"},
        {"kind": "deny_command", "target": "taint",
         "description": "Tainting nodes is not allowed"},
        {"kind": "deny_flag", "target": "--force",
         "description": "Force operations are too risky"},
    ],
    abstract_rules=[
        "This is a read-only policy. Only use get, describe, logs, and top commands.",
        "Do not attempt to work around these restrictions by using exec to run mutating commands inside pods."
    ]
)
```

Now the agent can run:

```
run_command("kubectl", ["get", "pods", "-n", "default", "-o", "json"])       # allowed
run_command("kubectl", ["describe", "pod", "my-pod", "-n", "staging"])       # allowed
run_command("kubectl", ["logs", "my-pod", "-n", "default", "--tail", "50"])   # allowed
```

But these are blocked:

```
run_command("kubectl", ["delete", "pod", "my-pod"])       # blocked: deny_command
run_command("kubectl", ["apply", "-f", "manifest.yaml"])  # blocked: deny_command
run_command("kubectl", ["scale", "deploy/app", "--replicas=0"])  # blocked: deny_command
```

#### Namespace-restricted access

Allow mutations but only within a specific namespace:

```
set_policy("kubectl",
    deterministic_rules=[
        {"kind": "deny_command", "target": "delete",
         "description": "Deletions require manual approval"},
        {"kind": "deny_pattern", "target": "^(kube-system|kube-public|default)$",
         "description": "System namespaces are off-limits"},
        {"kind": "deny_flag", "target": "--all-namespaces",
         "description": "Cross-namespace operations are not allowed"},
        {"kind": "deny_flag", "target": "-A",
         "description": "Cross-namespace operations are not allowed (short form)"},
    ],
    abstract_rules=[
        "Only operate within the 'dev-team' namespace.",
        "Always specify the namespace explicitly with -n."
    ]
)
```

---

### Docker

Docker manages containers, images, volumes, and networks. An unconstrained
agent could pull untrusted images, remove running containers, or expose
host paths.

#### Safe container inspection

```
register_cli("docker", max_depth=2)

set_policy("docker",
    deterministic_rules=[
        {"kind": "deny_command", "target": "rm",
         "description": "Removing containers is not allowed"},
        {"kind": "deny_command", "target": "rmi",
         "description": "Removing images is not allowed"},
        {"kind": "deny_command", "target": "system.prune",
         "description": "System prune is too destructive"},
        {"kind": "deny_command", "target": "volume.rm",
         "description": "Removing volumes could cause data loss"},
        {"kind": "deny_command", "target": "network.rm",
         "description": "Removing networks is not allowed"},
        {"kind": "deny_command", "target": "push",
         "description": "Pushing images to registries is not allowed"},
        {"kind": "deny_command", "target": "login",
         "description": "Registry authentication is not allowed"},
        {"kind": "deny_flag", "target": "--privileged",
         "description": "Privileged containers are a security risk"},
        {"kind": "deny_flag", "target": "--force",
         "description": "Force operations skip safety checks"},
        {"kind": "deny_pattern", "target": "--volume=/",
         "description": "Mounting host root is too dangerous"},
    ],
    abstract_rules=[
        "This policy allows inspecting containers and images but prevents destructive changes.",
        "Do not run containers that expose host networking (--network=host) unless explicitly asked."
    ]
)
```

#### Development-only Docker

Allow most operations but prevent interaction with production registries:

```
set_policy("docker",
    deterministic_rules=[
        {"kind": "deny_command", "target": "push",
         "description": "Pushing to registries requires manual approval"},
        {"kind": "deny_command", "target": "login",
         "description": "Registry login is not allowed via agent"},
        {"kind": "deny_pattern", "target": "registry\\.prod\\.",
         "description": "Production registries are off-limits"},
        {"kind": "deny_flag", "target": "--privileged",
         "description": "Privileged mode is not allowed"},
    ],
    abstract_rules=[
        "Only use local development images. Do not pull from or push to production registries.",
        "Prefer 'docker compose' commands over raw 'docker run' when a compose file exists."
    ]
)
```

---

### GitHub CLI (`gh`)

The GitHub CLI can create issues, merge PRs, delete branches, manage
releases, and modify repository settings — all operations with
immediate external consequences.

#### Code review assistant (read-only)

```
register_cli("gh", max_depth=2)

set_policy("gh",
    deterministic_rules=[
        {"kind": "deny_command", "target": "pr.merge",
         "description": "Merging PRs requires human approval"},
        {"kind": "deny_command", "target": "pr.close",
         "description": "Closing PRs is not allowed"},
        {"kind": "deny_command", "target": "pr.create",
         "description": "Creating PRs requires human approval"},
        {"kind": "deny_command", "target": "issue.create",
         "description": "Creating issues is not allowed"},
        {"kind": "deny_command", "target": "issue.close",
         "description": "Closing issues is not allowed"},
        {"kind": "deny_command", "target": "release",
         "description": "All release operations are blocked"},
        {"kind": "deny_command", "target": "repo.delete",
         "description": "Repository deletion is absolutely not allowed"},
        {"kind": "deny_command", "target": "repo.rename",
         "description": "Repository renaming is not allowed"},
        {"kind": "deny_command", "target": "repo.edit",
         "description": "Editing repository settings is not allowed"},
        {"kind": "deny_command", "target": "secret",
         "description": "Managing secrets is not allowed"},
    ],
    abstract_rules=[
        "You are a code review assistant. You may view PRs, issues, and diffs, "
        "but do not make any changes to the repository.",
        "When reviewing, add comments via the conversation — not via gh commands."
    ]
)
```

Now the agent can:

```
run_command("gh", ["pr", "list", "--state", "open"])             # allowed
run_command("gh", ["pr", "view", "42", "--comments"])            # allowed
run_command("gh", ["pr", "diff", "42"])                          # allowed
run_command("gh", ["issue", "list", "--label", "bug"])           # allowed
```

But these are blocked:

```
run_command("gh", ["pr", "merge", "42"])                         # blocked
run_command("gh", ["issue", "create", "--title", "Bug report"])  # blocked
run_command("gh", ["release", "create", "v1.0.0"])               # blocked
```

#### PR triage bot

Allow the agent to label and comment on issues/PRs but not close or merge them:

```
set_policy("gh",
    deterministic_rules=[
        {"kind": "deny_command", "target": "pr.merge",
         "description": "Merging requires human approval"},
        {"kind": "deny_command", "target": "pr.close",
         "description": "Closing PRs requires human approval"},
        {"kind": "deny_command", "target": "issue.close",
         "description": "Closing issues requires human approval"},
        {"kind": "deny_command", "target": "release",
         "description": "Release management is not in scope"},
        {"kind": "deny_command", "target": "repo.delete",
         "description": "Deletion is absolutely not allowed"},
        {"kind": "deny_command", "target": "secret",
         "description": "Secret management is not in scope"},
    ],
    abstract_rules=[
        "You are a triage bot. You may add labels, assign reviewers, and post comments.",
        "Do not approve PRs — only request changes or leave informational comments.",
        "When in doubt, escalate to a human rather than taking action."
    ]
)
```

---

### AWS CLI (`aws`)

The AWS CLI covers hundreds of services. Even read-only access needs
guardrails because some commands can be expensive (e.g., scanning entire
DynamoDB tables) or expose sensitive data.

#### Cost-safe read-only access

```
register_cli("aws", max_depth=1)

set_policy("aws",
    deterministic_rules=[
        {"kind": "deny_command", "target": "s3.rm",
         "description": "Deleting S3 objects is not allowed"},
        {"kind": "deny_command", "target": "s3.mb",
         "description": "Creating S3 buckets is not allowed"},
        {"kind": "deny_command", "target": "s3.rb",
         "description": "Removing S3 buckets is not allowed"},
        {"kind": "deny_command", "target": "ec2.terminate-instances",
         "description": "Terminating EC2 instances is not allowed"},
        {"kind": "deny_command", "target": "ec2.run-instances",
         "description": "Launching EC2 instances is not allowed"},
        {"kind": "deny_command", "target": "iam",
         "description": "All IAM operations are blocked for safety"},
        {"kind": "deny_command", "target": "organizations",
         "description": "AWS Organizations management is blocked"},
        {"kind": "deny_command", "target": "sts.assume-role",
         "description": "Assuming different roles is not allowed"},
        {"kind": "deny_pattern", "target": "delete|remove|destroy|terminate|put|create|update",
         "description": "Mutating verbs are blocked across all services"},
    ],
    abstract_rules=[
        "This is a read-only policy for inspecting AWS resources.",
        "Avoid commands that scan large datasets — prefer filtered queries with --query or --max-items.",
        "Do not retrieve or display any secrets, passwords, or access keys."
    ]
)
```

#### S3 data pipeline operator

Allow the agent to manage objects in a specific S3 bucket but nothing else:

```
set_policy("aws",
    deterministic_rules=[
        {"kind": "deny_command", "target": "ec2",
         "description": "EC2 is out of scope"},
        {"kind": "deny_command", "target": "iam",
         "description": "IAM management is not allowed"},
        {"kind": "deny_command", "target": "s3.rb",
         "description": "Removing buckets is not allowed"},
        {"kind": "deny_command", "target": "s3.mb",
         "description": "Creating buckets is not allowed"},
        {"kind": "deny_pattern", "target": "s3://(?!data-pipeline-bucket)",
         "description": "Only the data-pipeline-bucket is accessible"},
        {"kind": "deny_flag", "target": "--recursive",
         "description": "Recursive operations need manual approval"},
    ],
    abstract_rules=[
        "You operate a data pipeline using the 'data-pipeline-bucket' S3 bucket.",
        "Always verify the destination path before copying or moving objects.",
        "Prefer 'aws s3 ls' before any write operation to check existing state."
    ]
)
```

---

### Terraform

Terraform manages infrastructure as code. A single `terraform destroy`
can tear down an entire environment, so even limited agent access needs
careful policy.

#### Plan-only access

```
register_cli("terraform", max_depth=1)

set_policy("terraform",
    deterministic_rules=[
        {"kind": "deny_command", "target": "apply",
         "description": "Applying changes requires human approval"},
        {"kind": "deny_command", "target": "destroy",
         "description": "Destroying infrastructure is absolutely not allowed"},
        {"kind": "deny_command", "target": "import",
         "description": "Importing resources could overwrite state"},
        {"kind": "deny_command", "target": "taint",
         "description": "Tainting forces resource recreation"},
        {"kind": "deny_command", "target": "untaint",
         "description": "Untainting should be done manually"},
        {"kind": "deny_command", "target": "state",
         "description": "State manipulation is too dangerous"},
        {"kind": "deny_command", "target": "workspace.delete",
         "description": "Deleting workspaces is not allowed"},
        {"kind": "deny_flag", "target": "-auto-approve",
         "description": "Auto-approve bypasses the confirmation prompt"},
    ],
    abstract_rules=[
        "You may only run 'terraform plan', 'terraform validate', 'terraform fmt', and 'terraform show'.",
        "Always run 'terraform plan' and present the output to the user before suggesting an apply.",
        "Never suggest 'terraform apply' with -auto-approve."
    ]
)
```

---

### Git

Even `git` deserves guardrails when an agent is working on a shared
repository or against upstream branches.

#### Safe contributor

```
register_cli("git", max_depth=2)

set_policy("git",
    deterministic_rules=[
        {"kind": "deny_command", "target": "push",
         "description": "Pushing requires explicit human approval"},
        {"kind": "deny_flag", "target": "--force",
         "description": "Force operations rewrite history"},
        {"kind": "deny_flag", "target": "--force-with-lease",
         "description": "Force-with-lease still rewrites history"},
        {"kind": "deny_command", "target": "reset",
         "description": "Reset can lose uncommitted work"},
        {"kind": "deny_command", "target": "clean",
         "description": "Clean deletes untracked files permanently"},
        {"kind": "deny_pattern", "target": "^(main|master|production|release)$",
         "description": "Protected branches cannot be targets"},
    ],
    abstract_rules=[
        "Work on feature branches only. Do not commit directly to main or master.",
        "Write meaningful commit messages — explain the 'why', not just the 'what'."
    ]
)
```

#### Local-only mode

Allow the agent full local git freedom but block all network operations:

```
set_policy("git",
    deterministic_rules=[
        {"kind": "deny_command", "target": "push",
         "description": "Network operations are disabled"},
        {"kind": "deny_command", "target": "pull",
         "description": "Network operations are disabled"},
        {"kind": "deny_command", "target": "fetch",
         "description": "Network operations are disabled"},
        {"kind": "deny_command", "target": "clone",
         "description": "Network operations are disabled"},
        {"kind": "deny_command", "target": "remote",
         "description": "Remote configuration is disabled"},
    ],
    abstract_rules=[
        "You are operating in local-only mode. All commits and branches are local.",
        "The user will handle syncing with remote repositories."
    ]
)
```

---

### Helm

Helm manages Kubernetes application packages (charts). It can install,
upgrade, and delete releases — all with direct cluster impact.

```
register_cli("helm", max_depth=1)

set_policy("helm",
    deterministic_rules=[
        {"kind": "deny_command", "target": "install",
         "description": "Installing charts changes cluster state"},
        {"kind": "deny_command", "target": "upgrade",
         "description": "Upgrading releases changes cluster state"},
        {"kind": "deny_command", "target": "uninstall",
         "description": "Uninstalling releases removes running workloads"},
        {"kind": "deny_command", "target": "rollback",
         "description": "Rollbacks should be done manually"},
        {"kind": "deny_command", "target": "repo.remove",
         "description": "Removing chart repos is not allowed"},
    ],
    abstract_rules=[
        "You may search for charts, list releases, show values, and run 'helm template' for dry-run rendering.",
        "Always use 'helm template' to preview what would be deployed before suggesting an install or upgrade."
    ]
)
```

---

## Combining deterministic and abstract rules

The most effective policies combine both rule types:

- **Deterministic rules** are your hard perimeter — they cannot be circumvented.
- **Abstract rules** provide intent and nuance that deterministic rules cannot express.

For example, this `kubectl` policy blocks dangerous commands but also
guides the agent's behavior for allowed commands:

```
set_policy("kubectl",
    deterministic_rules=[
        {"kind": "deny_command", "target": "delete",
         "description": "Deletions require human approval"},
        {"kind": "deny_flag", "target": "--force",
         "description": "Force operations are not allowed"},
        {"kind": "deny_pattern", "target": "^(kube-system|kube-public)$",
         "description": "System namespaces are off-limits"},
    ],
    abstract_rules=[
        "Prefer 'get -o yaml' over 'describe' when you need structured output.",
        "Always check the namespace before running any command.",
        "If a pod is in CrashLoopBackOff, check its logs before suggesting a fix.",
        "When listing resources, limit output with --field-selector or --label-selector "
        "rather than fetching everything."
    ]
)
```

## Policy lifecycle

Policies are persisted in the same SQLite database as tool registrations
and survive across server restarts.

```
set_policy("kubectl", ...)     # Create or replace the policy
get_policy("kubectl")          # View the current policy
inspect_cli("kubectl")         # Policy is included in inspection results
run_command("kubectl", [...])  # Deterministic rules enforced automatically
remove_policy("kubectl")       # Remove all restrictions
```

Updating a policy **replaces** it entirely — there is no incremental
add/remove for individual rules. To modify a policy, retrieve it with
`get_policy`, adjust the rules, and call `set_policy` again with the
complete set.
