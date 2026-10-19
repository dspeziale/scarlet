"""Relationship graph of a resource: owners, children, selected pods, services, volumes, config, node.

Output: {"nodes": [{id, kind, name, namespace, health}], "edges": [{from, to, type}]}
Edge types: owns, selects, routes, mounts, uses, runs_on, binds, provisions.
"""

from __future__ import annotations

from typing import Any

from .summarize import summarize


def _id(kind: str, name: str, ns: str | None) -> str:
    return f"{kind}/{ns or ''}/{name}"


def _matches(selector: dict[str, str], labels: dict[str, str]) -> bool:
    return bool(selector) and all(labels.get(k) == v for k, v in selector.items())


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str]] = set()

    def add(self, obj: dict[str, Any] | None, *, kind: str | None = None, name: str | None = None,
            ns: str | None = None, root: bool = False) -> str:  # fmt: skip
        if obj is not None:
            s = summarize(obj)
            nid = _id(s["kind"], s["name"], s["namespace"])
            node = {"id": nid, "kind": s["kind"], "name": s["name"], "namespace": s["namespace"],
                    "health": s["health"], "missing": False}  # fmt: skip
        else:
            nid = _id(kind or "", name or "", ns)
            node = {"id": nid, "kind": kind, "name": name, "namespace": ns, "health": "unknown", "missing": True}
        if root:
            node["root"] = True
        if nid not in self.nodes or root:
            self.nodes[nid] = node
        return nid

    def edge(self, a: str, b: str, t: str) -> None:
        self.edges.add((a, b, t))

    def result(self) -> dict[str, Any]:
        return {"nodes": list(self.nodes.values()),
                "edges": [{"from": a, "to": b, "type": t} for a, b, t in sorted(self.edges)]}  # fmt: skip


def build(root: dict[str, Any], ns_objects: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """ns_objects: lists for the root's namespace (pods, replicasets, deployments, statefulsets,
    daemonsets, jobs, cronjobs, services, ingresses, pvcs, configmaps, secrets) + cluster-scoped
    pvs, nodes, storageclasses."""
    g = _Graph()
    kind = root.get("kind")
    meta = root.get("metadata") or {}
    ns = meta.get("namespace")
    root_id = g.add(root, root=True)
    by_uid = {(o.get("metadata") or {}).get("uid"): o for lst in ns_objects.values() for o in lst}
    pods = ns_objects.get("pods") or []
    services = ns_objects.get("services") or []

    def children_of(obj: dict[str, Any], child_kind: str) -> list[dict[str, Any]]:
        uid = (obj.get("metadata") or {}).get("uid")
        return [o for o in ns_objects.get(child_kind, []) if any(
            r.get("uid") == uid for r in (o.get("metadata") or {}).get("ownerReferences") or [])]  # fmt: skip

    def owners_chain(obj: dict[str, Any], oid: str) -> None:
        for ref in (obj.get("metadata") or {}).get("ownerReferences") or []:
            owner = by_uid.get(ref.get("uid"))
            pid = g.add(owner, kind=ref.get("kind"), name=ref.get("name"), ns=ns)
            g.edge(pid, oid, "owns")
            if owner is not None:
                owners_chain(owner, pid)

    def pod_details(pod: dict[str, Any], pid: str) -> None:
        spec = pod.get("spec") or {}
        node_name = spec.get("nodeName")
        if node_name:
            node = next((n for n in ns_objects.get("nodes", []) if n["metadata"]["name"] == node_name), None)
            g.edge(pid, g.add(node, kind="Node", name=node_name), "runs_on")
        for v in spec.get("volumes") or []:
            claim = (v.get("persistentVolumeClaim") or {}).get("claimName")
            if claim:
                pvc = next((p for p in ns_objects.get("pvcs", []) if p["metadata"]["name"] == claim), None)
                cid = g.add(pvc, kind="PersistentVolumeClaim", name=claim, ns=ns)
                g.edge(pid, cid, "mounts")
                if pvc is not None:
                    pvc_details(pvc, cid)
            if v.get("configMap"):
                n = v["configMap"].get("name")
                cm = next((c for c in ns_objects.get("configmaps", []) if c["metadata"]["name"] == n), None)
                g.edge(pid, g.add(cm, kind="ConfigMap", name=n, ns=ns), "mounts")
            if v.get("secret"):
                n = v["secret"].get("secretName")
                sec = next((c for c in ns_objects.get("secrets", []) if c["metadata"]["name"] == n), None)
                g.edge(pid, g.add(sec, kind="Secret", name=n, ns=ns), "mounts")
        for c in spec.get("containers") or []:
            refs = [("ConfigMap", (e.get("configMapRef") or {}).get("name")) for e in c.get("envFrom") or []]
            refs += [("Secret", (e.get("secretRef") or {}).get("name")) for e in c.get("envFrom") or []]
            for e in c.get("env") or []:
                vf = e.get("valueFrom") or {}
                refs.append(("ConfigMap", (vf.get("configMapKeyRef") or {}).get("name")))
                refs.append(("Secret", (vf.get("secretKeyRef") or {}).get("name")))
            for rk, rn in refs:
                if not rn:
                    continue
                lst = ns_objects.get("configmaps" if rk == "ConfigMap" else "secrets", [])
                obj = next((o for o in lst if o["metadata"]["name"] == rn), None)
                g.edge(pid, g.add(obj, kind=rk, name=rn, ns=ns), "uses")

    def pvc_details(pvc: dict[str, Any], cid: str) -> None:
        vol = (pvc.get("spec") or {}).get("volumeName")
        if vol:
            pv = next((p for p in ns_objects.get("pvs", []) if p["metadata"]["name"] == vol), None)
            pvid = g.add(pv, kind="PersistentVolume", name=vol)
            g.edge(cid, pvid, "binds")
        sc = (pvc.get("spec") or {}).get("storageClassName")
        if sc:
            sco = next((s for s in ns_objects.get("storageclasses", []) if s["metadata"]["name"] == sc), None)
            g.edge(g.add(sco, kind="StorageClass", name=sc), cid, "provisions")

    def services_for(pod_list: list[dict[str, Any]]) -> None:
        for svc in services:
            sel = (svc.get("spec") or {}).get("selector") or {}
            matched = [p for p in pod_list if _matches(sel, (p.get("metadata") or {}).get("labels") or {})]
            if matched:
                sid = g.add(svc)
                for p in matched:
                    g.edge(sid, _id("Pod", p["metadata"]["name"], ns), "selects")
                ingresses_for(svc, sid)

    def ingresses_for(svc: dict[str, Any], sid: str) -> None:
        sname = svc["metadata"]["name"]
        for ing in ns_objects.get("ingresses", []):
            for r in (ing.get("spec") or {}).get("rules") or []:
                for p in (r.get("http") or {}).get("paths") or []:
                    if ((p.get("backend") or {}).get("service") or {}).get("name") == sname:
                        g.edge(g.add(ing), sid, "routes")

    def add_pods(pod_list: list[dict[str, Any]], parent: str) -> None:
        for p in pod_list:
            pid = g.add(p)
            g.edge(parent, pid, "owns")
            pod_details(p, pid)

    if kind == "Deployment":
        all_pods = []
        for rs in children_of(root, "replicasets"):
            rid = g.add(rs)
            g.edge(root_id, rid, "owns")
            rs_pods = children_of(rs, "pods")
            add_pods(rs_pods, rid)
            all_pods += rs_pods
        services_for(all_pods)
    elif kind in ("StatefulSet", "DaemonSet", "ReplicaSet", "Job"):
        owners_chain(root, root_id)
        p = children_of(root, "pods")
        add_pods(p, root_id)
        services_for(p)
    elif kind == "CronJob":
        for job in children_of(root, "jobs"):
            jid = g.add(job)
            g.edge(root_id, jid, "owns")
            add_pods(children_of(job, "pods"), jid)
    elif kind == "Pod":
        owners_chain(root, root_id)
        pod_details(root, root_id)
        services_for([root])
    elif kind == "Service":
        sel = (root.get("spec") or {}).get("selector") or {}
        for p in pods:
            if _matches(sel, (p.get("metadata") or {}).get("labels") or {}):
                pid = g.add(p)
                g.edge(root_id, pid, "selects")
                owners_chain(p, pid)
        ingresses_for(root, root_id)
    elif kind == "Ingress":
        for r in (root.get("spec") or {}).get("rules") or []:
            for path in (r.get("http") or {}).get("paths") or []:
                sname = ((path.get("backend") or {}).get("service") or {}).get("name")
                if not sname:
                    continue
                svc = next((s for s in services if s["metadata"]["name"] == sname), None)
                sid = g.add(svc, kind="Service", name=sname, ns=ns)
                g.edge(root_id, sid, "routes")
                if svc is not None:
                    sel = (svc.get("spec") or {}).get("selector") or {}
                    for p in pods:
                        if _matches(sel, (p.get("metadata") or {}).get("labels") or {}):
                            g.edge(sid, g.add(p), "selects")
    elif kind == "PersistentVolumeClaim":
        pvc_details(root, root_id)
        for p in pods:
            for v in (p.get("spec") or {}).get("volumes") or []:
                if (v.get("persistentVolumeClaim") or {}).get("claimName") == meta.get("name"):
                    g.edge(g.add(p), root_id, "mounts")
    elif kind in ("ConfigMap", "Secret"):
        for p in pods:
            if str(meta.get("name")) in str(p.get("spec") or {}):
                pid = g.add(p)
                pod_details(p, pid)
    elif kind == "Node":
        for p in pods:
            if (p.get("spec") or {}).get("nodeName") == meta.get("name"):
                g.edge(g.add(p), root_id, "runs_on")
    elif kind == "PersistentVolume":
        claim = (root.get("spec") or {}).get("claimRef") or {}
        if claim:
            pvc = next((p for p in ns_objects.get("pvcs", []) if p["metadata"]["name"] == claim.get("name")
                        and p["metadata"].get("namespace") == claim.get("namespace")), None)  # fmt: skip
            g.edge(g.add(pvc, kind="PersistentVolumeClaim", name=claim.get("name"), ns=claim.get("namespace")),
                   root_id, "binds")  # fmt: skip
    # Only keep edges whose endpoints exist (pods referenced by id but not added).
    result = g.result()
    ids = {n["id"] for n in result["nodes"]}
    result["edges"] = [e for e in result["edges"] if e["from"] in ids and e["to"] in ids]
    return result
