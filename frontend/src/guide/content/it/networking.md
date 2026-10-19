---
title: Networking
summary: Come comunicano Pod, Service e mondo esterno - rete dei Pod, DNS ed endpoint.
category: networking
order: 30
keywords: rete, networking, cni, dns, coredns, endpoints, endpointslice, networkpolicy, kube-proxy
related: service, ingress, pod, node, troubleshooting, cluster
---

## In parole semplici

In Kubernetes **ogni Pod ha il suo indirizzo IP** e può parlare con qualsiasi altro Pod del cluster, su qualunque nodo, senza NAT. I [Service](guide:service) danno nomi stabili ai gruppi di Pod, il **DNS interno** traduce quei nomi in indirizzi e gli [Ingress](guide:ingress) aprono l'accesso dall'esterno.

Quando "un'applicazione non raggiunge l'altra", il problema sta quasi sempre in uno di questi quattro livelli: rete dei Pod, DNS, Service/endpoint, regole di sicurezza.

## Dettagli tecnici

- **Rete dei Pod (CNI)**: un plugin CNI (Calico, Cilium, Flannel, OVN-Kubernetes...) assegna gli IP dal *pod CIDR* e instrada il traffico tra nodi. Gira di solito come [DaemonSet](guide:daemonset): se si rompe su un nodo, quel nodo diventa spesso NotReady o i suoi Pod restano senza rete.
- **Service CIDR**: gli IP virtuali dei Service provengono da un intervallo separato. kube-proxy (o il CNI in modalità eBPF) traduce questi IP verso gli IP reali dei Pod.
- **Endpoint**: per ogni Service con selector, il control plane mantiene oggetti **EndpointSlice** (e il vecchio oggetto `Endpoints`) con gli IP dei Pod pronti. Un Pod non Ready finisce in `notReadyAddresses`/condizione `ready: false`.
- **DNS (CoreDNS)**: risolve `<service>.<namespace>.svc.cluster.local`. Dentro lo stesso namespace basta `<service>`; da un altro namespace serve almeno `<service>.<namespace>`. Il file `/etc/resolv.conf` del Pod punta al Service `kube-dns` in `kube-system` e usa `ndots:5`, quindi i nomi esterni brevi generano alcune ricerche in più.
- **NetworkPolicy**: se in un namespace esiste una policy che seleziona un Pod, quel Pod accetta solo il traffico esplicitamente consentito. Funzionano solo se il CNI le supporta.
- **Firewall del nodo**: su Oracle Linux `firewalld` può bloccare le porte di kubelet (10250), NodePort o il traffico del CNI (VXLAN 4789/UDP, BGP 179/TCP a seconda del plugin).

In Scarlet: [Networking → Endpoints](app:/k8s/endpoints) mostra quali Pod ricevono traffico per ogni Service.

## Esempio

Test rapido di DNS e connettività da un Pod temporaneo (alternativa da shell):

```bash
kubectl -n shop run nettest --rm -it --restart=Never \
  --image=docker.io/library/busybox:1.36 -- sh
# all'interno del Pod:
nslookup web
nslookup web.shop.svc.cluster.local
wget -qO- http://web:80/healthz
```

## Cosa può andare storto

- **DNS non risponde**: Pod di CoreDNS non pronti, oppure il traffico UDP/TCP 53 verso di essi è bloccato.
- **Service senza endpoint**: selector errato o Pod non Ready.
- **Pod che non comunicano tra nodi diversi**: CNI guasto, MTU errato (tipico con VXLAN/VPN: i pacchetti piccoli passano, quelli grandi no), firewall del nodo.
- **NetworkPolicy troppo restrittiva**, ad esempio un `deny-all` che blocca anche il DNS in uscita.
- **Sovrapposizione di indirizzi**: pod CIDR o service CIDR uguali a reti aziendali, con traffico instradato nel posto sbagliato.

## Come verificare

1. In Scarlet controlla gli [Endpoints](app:/k8s/endpoints) del Service interessato.
2. Verifica lo stato dei Pod di CoreDNS e del CNI in `kube-system` dalla pagina [Pod](app:/k8s/pods).
3. Cerca eventi di rete in [Cluster → Eventi](app:/cluster/events).

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system get pods -o wide | grep -Ei 'calico|cilium|flannel|kube-proxy'
kubectl get networkpolicy -A
```

## Come risolvere

1. Parti dal livello più basso: se due Pod non si raggiungono per IP, il problema è il CNI o il firewall, non il DNS.
2. Se gli IP funzionano ma i nomi no, controlla CoreDNS (log e stato dei Pod).
3. Se il nome risolve ma non ci sono endpoint, correggi selector o readiness del [Service](guide:service).
4. Rivedi le NetworkPolicy del namespace, permettendo sempre il DNS in uscita.
5. Per l'accesso dall'esterno vedi [Ingress](guide:ingress); per un metodo generale vedi [Troubleshooting](guide:troubleshooting).
