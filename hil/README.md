# CubeSatSim HIL

The HIL tools run on the control PC and communicate with the Raspberry Pi over SSH. 

**PROBE** 
Acts as a read-only probe: it establishes that(/if) the remote connection and 
the current CubeSatSim runtime are observable w/o doing any sensor injection

Run from the repository root:

```sh:
python3 hil/probe.py --host cubesatsim.local --user pi

#or

python3 hil/probe.py --host cubesatsim.local --user pi --json   #for machine-readable output
```

The probe checks the `cubesatsim` and `transmit` services, current mode,
simulation flags, I2C device nodes, and payload UART availability. It does not
restart services, change configuration, access GPIO, or transmit RF.



**JSON PARSER**
sample dei sensor -> into json parsing such as:
 
```json
{
  "power": {
    "batery": {"voltage": 3.88, "current": 420},
    "solar": {"voltage": 5.1, "current": 120}
  }
  "mode": {
    "mode: "f",
    "simulating": "true"
  }
  [..etc]
}
```



**PROPER HIL (o genere)**

w/ graphic html? o rust 0-0