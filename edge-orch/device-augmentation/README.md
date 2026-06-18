# Device Augmentation CRDs

This directory defines the Kubernetes-native surface for resource augmentation of
edge devices such as Jetson, Raspberry Pi, and industrial gateways.

The CRDs and the included controller provide a read-only management surface.
The controller reconciles status from the current `state-aggregator` virtual
resource observation. It does not perform automatic offloading, runtime
migration, workload creation, or Device CR mutation.

## Resources

- `AugmentationResource`: cluster-scoped compute or storage resource that can
  augment an edge device.
- `DeviceAugmentation`: namespaced binding from an edge device to one or more
  augmentation resources.

## Apply

```bash
kubectl apply -k edge-orch/device-augmentation/crds
kubectl apply -k edge-orch/device-augmentation/samples
kubectl apply -k edge-orch/device-augmentation/k8s
```

For the packaged service scenario, apply the scenario overlay instead of the
raw samples:

```bash
kubectl apply -k edge-orch/device-augmentation/crds
kubectl apply -k edge-orch/device-augmentation/scenarios/jetson-vision-inspection
kubectl apply -k edge-orch/device-augmentation/k8s
```

The scenario represents `etri-dev0001-jetorn` as an augmented Jetson device that
uses `vd-x86-gpu-inference` and `vd-storage-cache` through
`jetson-gpu-storage-augmentation`.

## Inspect

```bash
kubectl get augmentationresources
kubectl describe augmentationresource vd-x86-gpu-inference
kubectl get augmentationresource vd-x86-gpu-inference -o yaml

kubectl get deviceaugmentations -n default
kubectl describe deviceaugmentation jetson-gpu-storage-augmentation -n default
kubectl get deviceaugmentation jetson-gpu-storage-augmentation -n default -o yaml

kubectl get deployment device-augmentation-controller -n default
kubectl logs -n default deploy/device-augmentation-controller --tail=100
python3 tools/check_resource_augmentation_scenario.py --base-url http://127.0.0.1:8000
```

Status fields to inspect:

- `AugmentationResource.status.conditions`: runtime observation and endpoint readiness.
- `DeviceAugmentation.status.conditions`: binding, capability, resource, and ready checks.
- `DeviceAugmentation.status.selectedResources`: the resolved resource roles, nodes, and endpoint flags.

## Boundary

The controller reconciles status only:

1. Read `AugmentationResource` and `DeviceAugmentation`.
2. Read virtual resource observation from `state-aggregator`.
3. Update CRD `status`.
4. Leave workload deployment and offloading execution manual.
