---
title: Introduction to Scarlet
summary: What Scarlet is, how to tell LIVE mode from DEMO mode, and how to use this guide.
category: intro
order: 10
keywords: introduction, scarlet, pkm, live, demo, guide, method, operations center
related: cos-e-kubernetes, cos-e-podman, troubleshooting, proc-installare, faq
---

## What Scarlet is

**Scarlet** (*Secure Cluster Administration, Runtime & Lifecycle Engineering Tool*) is a web operations console that lets you manage a **Kubernetes** cluster and one or more **Podman** hosts from a single place. It is built for the people who keep applications running day to day: checking status, understanding why something is broken, acting safely, and leaving a record of what was done.

Scarlet does not replace `kubectl` or `podman`; it complements them. Everything you do in the interface goes through the official APIs (the Kubernetes API server and Podman's libpod REST API), with the permissions of the role assigned to your user. Every relevant operation is recorded in the [Audit Log](app:/security/audit).

The main areas of the left sidebar are:

- **Dashboard** and **Centro Operativo** (Operations Center): an overview of the state and the list of automatically detected problems, with severity (CRITICAL, ERROR, WARNING, INFO), risk and suggested actions.
- **Cluster**, **Applicazioni**, **Networking**, **Storage**, **Configurazione**: Kubernetes resources.
- **Container**: the Podman section (containers, images, registries).
- **Monitoraggio** and **Operazioni**: metrics, logs, system health, high availability; image onboarding and guided deploy, scale, restart, rollout, YAML apply, backup, node maintenance.
- **Sicurezza** and **Impostazioni**: users, roles, audit, application settings.

Every resource has a detail page with the tabs **Panoramica** (overview), **Relazioni** (relations), **Eventi** (events), **Log** (for pods), **Metriche** (metrics), **YAML** and **Diagnostica** (diagnostics).

## LIVE and DEMO modes

Scarlet can run in two modes, set in `/etc/pkm/config.yaml`:

| Mode | How to recognize it | Data shown |
|---|---|---|
| **LIVE** | Green "LIVE" badge with the cluster context name | Real cluster and Podman data |
| **DEMO** | Striped "DEMO" banner at the top | Sample data, no real cluster |

DEMO mode (`mode: demo`, accepted only with `environment: development`) is for training and trying out the interface. **Never use it in production**: actions have no effect on real systems and the data represent nothing real. Before any intervention, always look at the badge at the top: if you do not see "LIVE" with the expected context, stop.

> Scarlet never invents data. If metrics-server or Prometheus are not configured, metrics pages show "Metriche avanzate non configurate" (advanced metrics not configured) instead of fake values.

## How to use this guide

The guide is organized by category:

- **Introduction**: what Kubernetes is, what Podman is, this page.
- **Concepts**, **Workloads**, **Networking**, **Storage**, **Configuration**, **Reliability**: explain the objects you work with. Every article always has the same six sections: *In simple terms*, *Technical details*, *Example*, *What can go wrong*, *How to verify*, *How to fix*.
- **Troubleshooting**: one article for each typical error state (CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending...).
- **Procedures**: numbered steps for operational tasks (installing, connecting the cluster, rolling back, putting a node into maintenance, backup and restore...).
- **FAQ**: quick answers to the most common questions.

You can search by keyword from the **Guida** (Guide) page in the left sidebar and follow the "related" links at the end of each article. Where useful, articles also show the equivalent `kubectl` or `podman` commands, to be run on a shell if you have administrative access.

## The method: Understand, Diagnose, Decide, Act, Verify

When facing a problem, always follow these five steps (in the Italian interface: *Capire, Diagnosticare, Decidere, Agire, Verificare*). They prevent "gut-feeling" interventions that often make things worse.

1. **Understand**: what is happening and how serious is it? Start from the [Operations Center](app:/operations-center): it tells you which resource is affected, with what severity, and what the risk is.
2. **Diagnose**: why is it happening? Open the resource and look at the **Eventi**, **Log** and **Diagnostica** tabs. Read the guide article linked to the problem.
3. **Decide**: which intervention is the smallest and most reversible? A rollback is almost always safer than a live change. If the service is critical, notify the right people first.
4. **Act**: perform the action from the right page (Operazioni, Rollout, YAML with dry-run). Your role determines what you can do.
5. **Verify**: is the problem gone? Check that the pod is Ready, that events show no new errors, and that the Operations Center no longer flags the resource. Then mark the problem as handled from the Notification Center (bell icon).

## Roles in brief

- **Administrator**: can do everything, including settings, users, and revealing Secret values (an audited action).
- **Operator**: monitoring, deploy (wizard and YAML of application kinds), scale, restart, rollout, logs, troubleshooting, start/stop/restart of Podman containers.
- **Viewer**: read only, no logs and no Secret values.

Permissions are enforced by the backend: if a button is missing or returns an authorization error, your role does not allow that action.
