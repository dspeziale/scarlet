"""Scarlet - inventario dei rilasci.

Applicazione di riferimento della piattaforma Docker interna. Espone:

* ``GET /health``  liveness (il processo risponde);
* ``GET /ready``   readiness (database raggiungibile e schema allineato);
* ``GET /version`` versione, commit, immagine in esecuzione;
* ``GET /api/...`` API REST dell'inventario;
* ``GET /``        pagina HTML riepilogativa.
"""
