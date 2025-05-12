"""
BFO-2020 Definitions Module.

This module contains the core class and relation definitions from BFO-2020 (Basic Formal Ontology).
Based on the official BFO-2020 release (https://github.com/BFO-ontology/BFO-2020).
"""

# BFO-2020 Classes with labels, IRIs and descriptions
BFO_2020_CLASSES = {
    "entity": {
        "id": "entity",
        "label": "Entity",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000001",
        "description": "BFO-2020: A thing that exists."
    },
    "continuant": {
        "id": "continuant",
        "label": "Continuant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000002",
        "description": "BFO-2020: An entity that persists, endures, or continues to exist through time while maintaining its identity."
    },
    "occurrent": {
        "id": "occurrent",
        "label": "Occurrent",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000003",
        "description": "BFO-2020: An entity that unfolds itself in time or has temporal parts."
    },
    "independent_continuant": {
        "id": "independent_continuant",
        "label": "Independent Continuant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000004",
        "description": "BFO-2020: A continuant that is a bearer of quality and realizable entity entities, in which other entities inhere and which itself cannot inhere in anything."
    },
    "specifically_dependent_continuant": {
        "id": "specifically_dependent_continuant",
        "label": "Specifically Dependent Continuant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000020",
        "description": "BFO-2020: A continuant that depends on one or more specific independent continuants for its existence."
    },
    "generically_dependent_continuant": {
        "id": "generically_dependent_continuant",
        "label": "Generically Dependent Continuant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000031",
        "description": "BFO-2020: A continuant that is dependent on one or more other entities and can migrate from one bearer to another through a process of copying."
    },
    "process": {
        "id": "process",
        "label": "Process",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000015",
        "description": "BFO-2020: An occurrent that has temporal proper parts and for some time t, p s-depends_on some material entity at t."
    },
    "material_entity": {
        "id": "material_entity",
        "label": "Material Entity",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000040",
        "description": "BFO-2020: An independent continuant that has some portion of matter as part."
    },
    "immaterial_entity": {
        "id": "immaterial_entity",
        "label": "Immaterial Entity",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000141",
        "description": "BFO-2020: An independent continuant that contains no material entities as parts."
    },
    "spatial_region": {
        "id": "spatial_region",
        "label": "Spatial Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000006",
        "description": "BFO-2020: An immaterial entity that is part of space."
    },
    "quality": {
        "id": "quality",
        "label": "Quality",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000019",
        "description": "BFO-2020: A specifically dependent continuant that is exhibited if it inheres in an entity."
    },
    "realizable_entity": {
        "id": "realizable_entity",
        "label": "Realizable Entity",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000017",
        "description": "BFO-2020: A specifically dependent continuant that inheres in continuant entities and are not exhibited in full at every time in which they inhere."
    },
    "role": {
        "id": "role",
        "label": "Role",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000023",
        "description": "BFO-2020: A realizable entity that exists because its bearer is in some special physical, social, or institutional set of circumstances."
    },
    "disposition": {
        "id": "disposition",
        "label": "Disposition",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000016",
        "description": "BFO-2020: A realizable entity that when triggered or realized by an appropriate stimulus or background condition gives rise to a process of a certain kind."
    },
    "function": {
        "id": "function",
        "label": "Function",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000034",
        "description": "BFO-2020: A disposition that exists in virtue of the bearer's physical makeup and that is of a type instantiated in the evolutionary history of the bearer."
    },
    "site": {
        "id": "site",
        "label": "Site",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000029",
        "description": "BFO-2020: An immaterial entity that is a continuant part of a material entity."
    },
    "object": {
        "id": "object",
        "label": "Object",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000030",
        "description": "BFO-2020: A material entity that is spatially extended, exists as a whole at any time it exists, and has causal unity."
    },
    "object_aggregate": {
        "id": "object_aggregate",
        "label": "Object Aggregate",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000027",
        "description": "BFO-2020: A material entity that is a collection of objects, where the identity is determined by the members."
    },
    "fiat_object_part": {
        "id": "fiat_object_part",
        "label": "Fiat Object Part",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000024",
        "description": "BFO-2020: A material entity that is part of an object but is not demarcated by any physical discontinuities."
    },
    "process_boundary": {
        "id": "process_boundary",
        "label": "Process Boundary",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000035",
        "description": "BFO-2020: A temporal boundary of a process."
    },
    "temporal_region": {
        "id": "temporal_region",
        "label": "Temporal Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000008",
        "description": "BFO-2020: An occurrent that is part of time."
    },
    "continuant_fiat_boundary": {
        "id": "continuant_fiat_boundary",
        "label": "Continuant Fiat Boundary",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000140",
        "description": "BFO-2020: A fiat boundary that is a continuant."
    },
    "zero_dimensional_spatial_region": {
        "id": "zero_dimensional_spatial_region",
        "label": "Zero Dimensional Spatial Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000018",
        "description": "BFO-2020: A spatial region that is of zero dimensions, i.e., a spatial point."
    },
    "one_dimensional_spatial_region": {
        "id": "one_dimensional_spatial_region",
        "label": "One Dimensional Spatial Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000026",
        "description": "BFO-2020: A spatial region that is of one dimension, i.e., a spatial line."
    },
    "two_dimensional_spatial_region": {
        "id": "two_dimensional_spatial_region",
        "label": "Two Dimensional Spatial Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000009",
        "description": "BFO-2020: A spatial region that is of two dimensions, i.e., a spatial plane."
    },
    "three_dimensional_spatial_region": {
        "id": "three_dimensional_spatial_region",
        "label": "Three Dimensional Spatial Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000028",
        "description": "BFO-2020: A spatial region that is of three dimensions, i.e., a spatial volume."
    },
    "history": {
        "id": "history",
        "label": "History",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000182",
        "description": "BFO-2020: A process that is the sum of all processes taking place in the spatiotemporal region occupied by a material entity or site."
    },
    "relational_quality": {
        "id": "relational_quality",
        "label": "Relational Quality",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000145",
        "description": "BFO-2020: A quality that depends on at least two independent entities."
    },
    "spatiotemporal_region": {
        "id": "spatiotemporal_region",
        "label": "Spatiotemporal Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000011",
        "description": "BFO-2020: An occurrent that is part of spacetime."
    },
    "temporal_instant": {
        "id": "temporal_instant",
        "label": "Temporal Instant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000148",
        "description": "BFO-2020: A zero-dimensional temporal region that is a boundary of a temporal interval."
    },
    "connected_temporal_region": {
        "id": "connected_temporal_region",
        "label": "Connected Temporal Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000311",
        "description": "BFO-2020: A temporal region that is not the union of two or more disconnected temporal regions."
    },
    "scattered_temporal_region": {
        "id": "scattered_temporal_region",
        "label": "Scattered Temporal Region",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000032",
        "description": "BFO-2020: A temporal region that is the mereological sum of two or more connected temporal regions which are not themselves connected to each other."
    },
    "process_profile": {
        "id": "process_profile",
        "label": "Process Profile",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000144",
        "description": "BFO-2020: A proper part of a process that is itself a process and that unfolds during a proper part of the time during which the whole process unfolds."
    }
}

# BFO-2020 Relations with labels, IRIs and descriptions
BFO_2020_RELATIONS = {
    "part_of": {
        "id": "part_of",
        "label": "Part Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000050",
        "description": "BFO-2020: A core relation that holds between a part and its whole."
    },
    "has_part": {
        "id": "has_part",
        "label": "Has Part",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000051",
        "description": "BFO-2020: A core relation that holds between a whole and its part."
    },
    "located_in": {
        "id": "located_in",
        "label": "Located In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000082",
        "description": "BFO-2020: A relation between a continuant and a spatial region it occupies."
    },
    "location_of": {
        "id": "location_of",
        "label": "Location Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000124",
        "description": "BFO-2020: A relation between a spatial region and a continuant that occupies it."
    },
    "contained_in": {
        "id": "contained_in",
        "label": "Contained In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000082",
        "description": "BFO-2020: A relation between a material entity and a site that contains it."
    },
    "contains": {
        "id": "contains",
        "label": "Contains",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000081",
        "description": "BFO-2020: A relation between a site and a material entity that is contained within it."
    },
    "participates_in": {
        "id": "participates_in",
        "label": "Participates In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000056",
        "description": "BFO-2020: A relation between a continuant and a process in which it participates."
    },
    "has_participant": {
        "id": "has_participant",
        "label": "Has Participant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000057",
        "description": "BFO-2020: A relation between a process and a continuant that participates in it."
    },
    "bearer_of": {
        "id": "bearer_of",
        "label": "Bearer Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000053",
        "description": "BFO-2020: A relation between an independent continuant and a specifically dependent continuant that inheres in it."
    },
    "inheres_in": {
        "id": "inheres_in",
        "label": "Inheres In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000052",
        "description": "BFO-2020: A relation between a specifically dependent continuant and an independent continuant that bears it."
    },
    "realized_in": {
        "id": "realized_in",
        "label": "Realized In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000054",
        "description": "BFO-2020: A relation between a realizable entity and a process in which it is realized."
    },
    "realizes": {
        "id": "realizes",
        "label": "Realizes",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000055",
        "description": "BFO-2020: A relation between a process and a realizable entity that it realizes."
    },
    "exists_at": {
        "id": "exists_at",
        "label": "Exists At",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000108",
        "description": "BFO-2020: A relation between a continuant and a temporal region at which it exists."
    },
    "instance_of": {
        "id": "instance_of",
        "label": "Instance Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000110",
        "description": "BFO-2020: The relation between an instance and the class of which it is an instance."
    },
    "occurs_in": {
        "id": "occurs_in",
        "label": "Occurs In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000066",
        "description": "BFO-2020: A relation between a process and a material entity or site where it occurs."
    },
    "has_quality": {
        "id": "has_quality",
        "label": "Has Quality",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000086",
        "description": "BFO-2020: A relation between an independent continuant and a quality that inheres in it."
    },
    "quality_of": {
        "id": "quality_of",
        "label": "Quality Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000080",
        "description": "BFO-2020: A relation between a quality and the independent continuant in which it inheres."
    },
    "has_material_basis": {
        "id": "has_material_basis",
        "label": "Has Material Basis",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000127",
        "description": "BFO-2020: A relation between a disposition or function and its material basis."
    },
    "material_basis_of": {
        "id": "material_basis_of",
        "label": "Material Basis Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000126",
        "description": "BFO-2020: A relation between a material entity and the disposition or function for which it serves as basis."
    },
    "concretizes": {
        "id": "concretizes",
        "label": "Concretizes",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000059",
        "description": "BFO-2020: A relation between an specifically dependent continuant and the generically dependent continuant it concretizes."
    },
    "concretization_of": {
        "id": "concretization_of",
        "label": "Concretization Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000058",
        "description": "BFO-2020: A relation between a generically dependent continuant and the specifically dependent continuant that concretizes it."
    },
    "has_first_instant": {
        "id": "has_first_instant",
        "label": "Has First Instant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000153",
        "description": "BFO-2020: A relation between a connected temporal region and its first instant."
    },
    "has_last_instant": {
        "id": "has_last_instant",
        "label": "Has Last Instant",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000154",
        "description": "BFO-2020: A relation between a connected temporal region and its last instant."
    },
    "preceded_by": {
        "id": "preceded_by",
        "label": "Preceded By",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000060",
        "description": "BFO-2020: A relation between two occurrents, where one occurs before the other."
    },
    "precedes": {
        "id": "precedes",
        "label": "Precedes",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000061",
        "description": "BFO-2020: A relation between two occurrents, where one occurs before the other."
    },
    "spatially_contains": {
        "id": "spatially_contains",
        "label": "Spatially Contains",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000175",
        "description": "BFO-2020: A relation between two spatial regions where one contains the other."
    },
    "spatially_contained_in": {
        "id": "spatially_contained_in",
        "label": "Spatially Contained In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000176",
        "description": "BFO-2020: A relation between two spatial regions where one is contained in the other."
    },
    "temporally_contains": {
        "id": "temporally_contains",
        "label": "Temporally Contains",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000177",
        "description": "BFO-2020: A relation between two temporal regions where one contains the other."
    },
    "temporally_contained_in": {
        "id": "temporally_contained_in",
        "label": "Temporally Contained In",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000178",
        "description": "BFO-2020: A relation between two temporal regions where one is contained in the other."
    },
    "temporal_part_of": {
        "id": "temporal_part_of",
        "label": "Temporal Part Of",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000186",
        "description": "BFO-2020: A relation between a process and a process where one is a temporal part of the other."
    },
    "has_temporal_part": {
        "id": "has_temporal_part",
        "label": "Has Temporal Part",
        "uri": "http://purl.obolibrary.org/obo/BFO_0000187",
        "description": "BFO-2020: A relation between a process and a process where one has the other as a temporal part."
    }
}