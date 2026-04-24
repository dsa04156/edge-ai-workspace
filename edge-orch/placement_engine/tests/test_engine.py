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


def test_selective_policy_keeps_when_gain_below_margin():
    decision = decide_stage_placement(
        workflow_id="wf-selective-keep",
        stage_id="preprocess",
        node_profiles=NODE_PROFILES[:2],
        node_states=[
            {
                "hostname": "etri-ser0001-CG0MSB",
                "compute_pressure": "low",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "healthy",
            },
            {
                "hostname": "etri-dev0001-jetorn",
                "compute_pressure": "medium",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "healthy",
            },
        ],
        stage_metadata={
            "stage_type": "analysis",
            "requires_accelerator": False,
            "compute_intensity": "medium",
            "memory_intensity": "low",
            "latency_sensitivity": "medium",
            "input_size_kb": 128,
            "output_size_kb": 128,
        },
        current_placement="etri-dev0001-jetorn",
        stage_cost_stats=[
            {
                "stage_type": "analysis",
                "node": "etri-dev0001-jetorn",
                "sample_count": 3,
                "exec_median_ms": 1300.0,
                "exec_ema_ms": 1300.0,
                "queue_median_ms": 100.0,
                "warmup_median_ms": 180.0,
            },
            {
                "stage_type": "analysis",
                "node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "exec_median_ms": 1000.0,
                "exec_ema_ms": 1000.0,
                "queue_median_ms": 100.0,
                "warmup_median_ms": 150.0,
            },
        ],
        migration_cost_stats=[
            {
                "stage_type": "analysis",
                "from_node": "etri-dev0001-jetorn",
                "to_node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "migration_median_ms": 400.0,
                "migration_ema_ms": 400.0,
            }
        ],
        workflow_type="vision_pipeline",
    )

    assert decision.target_node == "etri-dev0001-jetorn"
    assert decision.action_type == "keep"
    assert decision.score_breakdown["selected_policy"] == "selective_keep_below_margin"


def test_selective_policy_migrates_when_gain_exceeds_margin():
    decision = decide_stage_placement(
        workflow_id="wf-selective-migrate",
        stage_id="preprocess",
        node_profiles=NODE_PROFILES[:2],
        node_states=[
            {
                "hostname": "etri-ser0001-CG0MSB",
                "compute_pressure": "low",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "healthy",
            },
            {
                "hostname": "etri-dev0001-jetorn",
                "compute_pressure": "high",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "degraded",
            },
        ],
        stage_metadata={
            "stage_type": "preprocess",
            "requires_accelerator": False,
            "compute_intensity": "medium",
            "memory_intensity": "low",
            "latency_sensitivity": "high",
            "input_size_kb": 512,
            "output_size_kb": 1024,
        },
        current_placement="etri-dev0001-jetorn",
        stage_cost_stats=[
            {
                "stage_type": "preprocess",
                "node": "etri-dev0001-jetorn",
                "sample_count": 3,
                "exec_median_ms": 2400.0,
                "exec_ema_ms": 2500.0,
                "queue_median_ms": 400.0,
                "warmup_median_ms": 240.0,
                "recent_migration_count_last_hour": 0,
                "placement_stability": "stable",
            },
            {
                "stage_type": "preprocess",
                "node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "exec_median_ms": 1100.0,
                "exec_ema_ms": 1100.0,
                "queue_median_ms": 50.0,
                "warmup_median_ms": 150.0,
                "recent_migration_count_last_hour": 0,
                "placement_stability": "stable",
            },
        ],
        migration_cost_stats=[
            {
                "stage_type": "preprocess",
                "from_node": "etri-dev0001-jetorn",
                "to_node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "migration_median_ms": 140.0,
                "migration_ema_ms": 150.0,
            }
        ],
        workflow_type="vision_pipeline",
    )

    assert decision.target_node == "etri-ser0001-CG0MSB"
    assert decision.action_type == "offload_to_cloud"
    assert decision.score_breakdown["selected_policy"] == "selective_migrate_above_margin"


def test_selective_policy_applies_instability_penalty():
    decision = decide_stage_placement(
        workflow_id="wf-unstable",
        stage_id="preprocess",
        node_profiles=NODE_PROFILES[:2],
        node_states=[
            {
                "hostname": "etri-ser0001-CG0MSB",
                "compute_pressure": "low",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "healthy",
            },
            {
                "hostname": "etri-dev0001-jetorn",
                "compute_pressure": "medium",
                "memory_pressure": "low",
                "network_pressure": "low",
                "node_health": "healthy",
            },
        ],
        stage_metadata={
            "stage_type": "preprocess",
            "requires_accelerator": False,
            "compute_intensity": "medium",
            "memory_intensity": "low",
            "latency_sensitivity": "high",
            "input_size_kb": 256,
            "output_size_kb": 256,
        },
        current_placement="etri-dev0001-jetorn",
        stage_cost_stats=[
            {
                "stage_type": "preprocess",
                "node": "etri-dev0001-jetorn",
                "sample_count": 3,
                "exec_median_ms": 1300.0,
                "exec_ema_ms": 1300.0,
                "queue_median_ms": 100.0,
                "warmup_median_ms": 220.0,
                "recent_migration_count_last_hour": 3,
                "placement_stability": "unstable",
            },
            {
                "stage_type": "preprocess",
                "node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "exec_median_ms": 1000.0,
                "exec_ema_ms": 1000.0,
                "queue_median_ms": 50.0,
                "warmup_median_ms": 150.0,
                "recent_migration_count_last_hour": 3,
                "placement_stability": "unstable",
            },
        ],
        migration_cost_stats=[
            {
                "stage_type": "preprocess",
                "from_node": "etri-dev0001-jetorn",
                "to_node": "etri-ser0001-CG0MSB",
                "sample_count": 3,
                "migration_median_ms": 150.0,
                "migration_ema_ms": 150.0,
            }
        ],
        workflow_type="vision_pipeline",
    )

    assert decision.action_type == "keep"
    assert decision.score_breakdown["decision_margin_ms"] == 1200.0
