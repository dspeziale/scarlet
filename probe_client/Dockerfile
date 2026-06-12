FROM python:3.11-slim

WORKDIR /app

# Installa le dipendenze di sistema (nmap, snmp, suricata, postgres)
RUN apt-get update && apt-get install -y nmap snmp libsnmp-dev suricata libpq-dev postgresql-client tcpdump iw wireless-tools bluez bluetooth git && rm -rf /var/lib/apt/lists/*

# Installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY . .

# Esponi la porta della dashboard
EXPOSE 5001

# Variabili d'ambiente di default
ENV PORT=5001
ENV SERVER_URL="http://host.docker.internal:5000"

# Avvia l'applicazione Flask
CMD ["python", "app.py"]
