# Example: Kubernetes application

    python scripts/build-scarlet-package.py --source examples/kubernetes-app --version 1.0.0 --output dist/

The target host must have runtime KUBERNETES. SCARLET either runs `kubectl` on the host over SSH
(default) or talks to the Kubernetes API with a kubeconfig credential attached to the host.
Objects are labelled `scarlet.io/application` and `scarlet.io/version`; rollback re-applies the
previous release's manifests. Pin image tags: every release must be immutable.
