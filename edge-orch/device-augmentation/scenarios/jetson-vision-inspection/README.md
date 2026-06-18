# Jetson Vision Inspection Resource Augmentation Scenario

This scenario is the deployable sample for a resource-augmentation virtual
device workflow.

## Story

`etri-dev0001-jetorn` remains the physical target device. The device is treated
as augmented when the Kubernetes `DeviceAugmentation` named
`jetson-gpu-storage-augmentation` is `Ready` and its selected resources are:

- `vd-x86-gpu-inference` for heavy vision inference
- `vd-storage-cache` for result windows, model cache, and output buffering

The physical device is not replaced and no virtual sensor is created.

## Apply

```bash
kubectl apply -k edge-orch/device-augmentation/crds
kubectl apply -k edge-orch/device-augmentation/scenarios/jetson-vision-inspection
kubectl apply -k edge-orch/device-augmentation/k8s
```

## Verify

```bash
python3 tools/check_resource_augmentation_scenario.py --base-url http://127.0.0.1:8000
kubectl get configmap resource-augmentation-scenario-jetson-vision-inspection -n default
kubectl get deviceaugmentation jetson-gpu-storage-augmentation -n default
kubectl get augmentationresource vd-x86-gpu-inference vd-storage-cache
```

Expected state:

- `DeviceAugmentation.status.phase=Ready`
- `DeviceAugmentation.status.selectedResources` includes inference and storage roles
- both selected `AugmentationResource` objects are `Available`
- dashboard `자원증강` tab shows the same binding as read-only/dry-run

This scenario does not create workloads, mutate KubeEdge `Device` CRs, publish
MQTT commands, run automatic offloading, or perform runtime migration.
