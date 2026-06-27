#!/usr/bin/env python3
"""Cteni cidel z TA CMI pres JSON API. Stdlib only -> jede na frantovi bez pip.
Usage:
  cmi_read.py HOST USER PASS [NODE] [PARAM]      # zive cteni
  cmi_read.py --file sample.json                  # test na vzorku
"""
import sys, json, base64, urllib.request

UNIT = {"0":"", "1":"°C", "2":"W/m²", "3":"l/h", "4":"s", "5":"min", "7":"K",
        "8":"%", "10":"kW", "11":"kWh", "12":"MWh", "13":"V", "14":"mA",
        "19":"l", "28":"m³", "43":"Aus/Ein", "44":"Nein/Ja", "46":"°C", "63":"A"}

def fetch(host, user, pw, node, param="I"):
    url = f"http://{host}/INCLUDE/api.cgi?jsonnode={node}&jsonparam={param}"
    req = urllib.request.Request(url)
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req.add_header("Authorization", f"Basic {tok}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

def show(data):
    hdr = data.get("Header", {})
    print(f"# device={hdr.get('Device')} ver={hdr.get('Version')} "
          f"ts={hdr.get('Timestamp')} status={data.get('Status')} "
          f"code={data.get('Status code', data.get('Statuscode'))}")
    inputs = data.get("Data", {}).get("Inputs", [])
    if not inputs:
        print("  !! zadne Inputs - spatny node/param nebo auth"); return
    for inp in inputs:
        v = inp.get("Value", {})
        unit = UNIT.get(str(v.get("Unit")), f"u{v.get('Unit')}")
        ad = inp.get("AD", "?")
        print(f"  Input {inp.get('Number'):>2} [{ad}]  {str(v.get('Value')):>8}  {unit}")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        data = json.load(open(sys.argv[2]))
    else:
        host, user, pw = sys.argv[1], sys.argv[2], sys.argv[3]
        node = sys.argv[4] if len(sys.argv) > 4 else "1"
        param = sys.argv[5] if len(sys.argv) > 5 else "I"
        data = fetch(host, user, pw, node, param)
    show(data)
