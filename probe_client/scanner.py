import nmap
from pysnmp.hlapi import *
import socket
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_snmp_sysdescr(ip, community='public'):
    try:
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community),
            UdpTransportTarget((ip, 161), timeout=1.0, retries=0),
            ContextData(),
            ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if not errorIndication and not errorStatus:
            for varBind in varBinds:
                return varBind[1].prettyPrint()
    except Exception:
        pass
    return None

def scan_network(subnet=None):
    logger.info("Starting network scan...")
    if not subnet:
        local_ip = get_local_ip()
        if local_ip == '127.0.0.1':
            logger.warning("Could not determine local IP. Skipping scan.")
            return {"devices": []}
            
        subnet = local_ip.rsplit('.', 1)[0] + '.0/24'
        
    logger.info(f"Scanning subnet: {subnet}")
    
    try:
        nm = nmap.PortScanner()
        # Scan rapido sulle top 100 porte, con OS detection limitato per velocità
        nm.scan(hosts=subnet, arguments='-T4 -F -O --osscan-limit --max-os-tries 1')
    except nmap.PortScannerError as e:
        logger.error(f"Nmap error: {e}")
        return {"devices": []}
    except Exception as e:
        logger.error(f"Unexpected scan error: {e}")
        return {"devices": []}
    
    devices = []
    for host in nm.all_hosts():
        if nm[host].state() != 'up':
            continue
            
        mac = nm[host]['addresses'].get('mac', '')
        hostname = nm[host].hostname()
        
        os_info = ''
        if 'osmatch' in nm[host] and len(nm[host]['osmatch']) > 0:
            os_info = nm[host]['osmatch'][0]['name']
            
        snmp_descr = None
        
        ports = []
        for proto in nm[host].all_protocols():
            lport = nm[host][proto].keys()
            for port in lport:
                state = nm[host][proto][port]['state']
                name = nm[host][proto][port]['name']
                version = nm[host][proto][port]['version']
                ports.append({
                    'port': port,
                    'protocol': proto,
                    'state': state,
                    'name': name,
                    'version': version
                })
                
        # Sempre un check SNMP rapido se raggiungibile
        snmp_descr = get_snmp_sysdescr(host)
            
        devices.append({
            'ip': host,
            'mac': mac,
            'hostname': hostname,
            'os': os_info,
            'snmp': snmp_descr,
            'ports': ports
        })
        
    logger.info(f"Scan complete. Found {len(devices)} devices.")
    return {"devices": devices}

def vuln_scan(target_ip):
    logger.info(f"Starting vulnerability scan on {target_ip}...")
    try:
        nm = nmap.PortScanner()
        # Escuzione dello script vuln di Nmap sulle porte aperte
        # -sV rileva i servizi e --script vuln prova a trovare vulnerabilità
        nm.scan(hosts=target_ip, arguments='-sV --script vuln')
    except Exception as e:
        logger.error(f"Vuln scan error: {e}")
        return {"error": str(e)}
        
    if target_ip not in nm.all_hosts() or nm[target_ip].state() != 'up':
        return {"error": "Host is down or unreachable."}
        
    results = {}
    for proto in nm[target_ip].all_protocols():
        lport = nm[target_ip][proto].keys()
        for port in lport:
            port_info = nm[target_ip][proto][port]
            if 'script' in port_info:
                # scripts is a dictionary of script_name -> output
                results[f"{port}/{proto}"] = port_info['script']
                
    if not results:
        # Check hostscripts just in case
        if 'hostscript' in nm[target_ip]:
            results["host"] = nm[target_ip]['hostscript']
            
    if not results:
        results = {"message": "No vulnerabilities found or scripts did not return any output."}
        
    return results
