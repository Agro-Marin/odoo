#!/usr/bin/env python3
from __future__ import annotations

import doc_gate  # noqa: F401  -- puts tooling/architecture on sys.path
from doc_gate._shared import (  # noqa: F401
    DOC,
    DOC_FLAT,
    DOC_PATH,
    DOC_PATHS,
    NUMBER_WORD_BY_VALUE,
    NUMBER_WORDS,
    ROOT,
    read_docs,
)
from doc_gate.citations import (  # noqa: F401
    TestCitationsResolve,
    TestContractNamesResolveEverywhere,
    TestPatchModuleConvention,
    TestPosture,
    TestReferencedArtifacts,
    TestTheFrontDoorIndexes,
)
from doc_gate.coupling_view import (  # noqa: F401
    TestCompositionDesignRule,
    TestCompositionTable,
    TestCountsRestatedElsewhere,
    TestMixinCount,
    TestPermissionIsNotPractice,
    TestRuntimeSurfaceFigures,
    TestSeams,
)
from doc_gate.gates_view import (  # noqa: F401
    TestAddonSuiteFigures,
    TestFloorMethodologyExample,
)
from doc_gate.module_view import (  # noqa: F401
    TestContractTable,
    TestEdgeCountConventions,
    TestLayerProse,
    TestOrmDocstringAgreesWithGate,
    TestPinnedCyclesAndRemovals,
    TestPinnedViolations,
    TestSubsystemMap,
    TestToolsIsTheFacadeForLibs,
    TestToolsReachesTheRuntime,
)
from doc_gate.register_view import (  # noqa: F401
    TestQualityFigureArithmetic,
    TestRiskRegisterFigures,
)
from doc_gate.runtime_view import (  # noqa: F401
    TestCronExceptionRationale,
    TestHttpCallGraphIsRecoverable,
    TestHttpLifecycle,
    TestLifecycleSketches,
    TestRuntimeFloors,
)
from doc_gate.stores_view import (  # noqa: F401
    TestDeploymentLimits,
    TestFilestoreLayout,
    TestSignallingTables,
)

if __name__ == "__main__":
    import unittest

    unittest.main()
