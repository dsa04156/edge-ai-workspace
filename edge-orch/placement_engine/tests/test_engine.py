from placement_engine.engine import decide_stage_placement, replan_workflow


NODE_PROFILES = [
    {
        "hostname": "etri-ser0001-CG0MSB",
        "node_type": "cloud_server",
        "arch": "x86_64",
        "compute_class": "high",
        "memory_class": "high",
        "accelerator_type": "gpu_discrete",
        "preferred_workload": ["large_model_serving"],
        "risky_workload": [],
    },
    {
        "hostname": "etri-dev0001-jetorn",
        "node_type": "edge_ai_device",
        "arch": "aarch64",
        "compute_class": "medium",
        "memory_class": "medium",
        "accelerator_type": "gpu_embedded",
        "preferred_workload": ["edge_inference", "preprocess"],
        "risky_workload": ["large_model_serving"],
    },
    {
        "hostname": "etri-dev0002-raspi5",
        "node_type": "edge_light_device",
        "arch": "aarch64",
        "compute_class": "low",
        "memory_class": "low",
        "accelerator_type": "none",
        "preferred_workload": ["preprocess"],
        "risky_workload": ["large_model_serving", "central_planner"],
    },
]

NODE_STATES = [
    {
        "hostname": "etri-ser0001-CG0MSB",
        "compute_pressure": "low",
        "memory_pressure": "low",
        "network_pressure": "low",
        "node_health": "healthy",
    },
    {
        "hostname": "etri-dev0001-jetorn",
        "compute_pressure": "low",
        "memory_pressure": "low",
        "network_pressure": "low",
        "node_health": "healthy",
    },
    {
        "hostname": "etri-dev0002-raspi5",
        "compute_pressure": "low",
        "memory_pressure": "low",
        "network_pressure": "low",
        "node_health": "healthy",
    },
]


def test_heavy_inference_prefers_server():
    decision = decide_stage_placement(
        workflow_id="wf-heavy",
        stage_id="infer",
        node_profiles=NODE_PROFILES,
        node_states=NODE_STATES,
        stage_metadata={
            "stage_type": "inference",
            "requires_accelerator": True,
            "compute_intensity": "high",
            "memory_intensity": "medium",
            "latency_sensitivity": "medium",
            "input_size_kb": 1024,
            "output_size_kb": 128,
        },
        current_placement="etri-dev0001-jetorn",
        workflow_type="large_model_serving",
    )

    assert decision.target_node == "etri-ser0001-CG0MSB"
    assert decision.action_type == "offload_to_cloud"


def test_source_near_stage_prefers_raspi():
    decision = decide_stage_placement(
        workflow_id="wf-source",
        stage_id="preprocess",
        node_profiles=NODE_PROFILES,
        node_states=NODE_STATES,
        stage_metadata={
            "stage_type": "preprocess",
            "requires_accelerator": False,
            "compute_intensity": "low",
            "memory_intensity": "low",
            "latency_sensitivity": "high",
            "input_size_kb": 32,
            "output_size_kb": 16,
        },
        workflow_type="preprocess",
    )

    assert decision.target_node == "etri-dev0002-raspi5"


def test_high_memory_pressure_blocks_heavy_stage():
    node_states = [dict(item) for item in NODE_STATES]
    node_states[1]["memory_pressure"] = "high"

    decision = decide_stage_placement(
        workflow_id="wf-edge",
        stage_id="infer",
        node_profiles=NODE_PROFILES,
        node_states=node_states,
        stage_metadata={
            "stage_type": "inference",
            "requires_accelerator": True,
            "compute_intensity": "high",
            "memory_intensity": "high",
            "latency_sensitivity": "high",
            "input_size_kb": 256,
            "output_size_kb": 64,
        },
        workflow_type="edge_inference",
    )

    assert decision.target_node == "etri-ser0001-CG0MSB"


def test_replan_workflow_returns_multiple_decisions():
    decisions = replan_workflow(
        workflow_id="wf-batch",
        stages=[
            {
                "stage_id": "capture",
                "stage_metadata": {
                    "stage_type": "capture",
                    "requires_accelerator": False,
                    "compute_intensity": "low",
                    "memory_intensity": "low",
                    "latency_sensitivity": "high",
                    "input_size_kb": 8,
                    "output_size_kb": 8,
                },
            },
            {
                "stage_id": "infer",
                "stage_metadata": {
                    "stage_type": "inference",
                    "requires_accelerator": True,
                    "compute_intensity": "high",
                    "memory_intensity": "medium",
                    "latency_sensitivity": "medium",
                    "input_size_kb": 512,
                    "output_size_kb": 64,
                },
            },
        ],
        node_profiles=NODE_PROFILES,
        node_states=NODE_STATES,
        current_placement={"capture": "etri-dev0002-raspi5", "infer": "etri-dev0001-jetorn"},
        workflow_type="edge_inference",
    )

    assert len(decisions) == 2
    assert decisions[0].action_type == "keep"
    assert decisions[1].target_node in {"etri-dev0001-jetorn", "etri-ser0001-CG0MSB"}
