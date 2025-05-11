/**
 * Ontology Visualizer
 * A JavaScript library for visualizing ontology class hierarchies and relationships
 * using the D3.js library
 */

// Function to initialize the visualization
function initializeOntologyVisualization(containerId, ontologyData) {
    // Get the container dimensions
    const container = document.getElementById(containerId);
    const width = container.clientWidth;
    const height = 600;
    
    // Calculate the central position
    const center = { x: width / 2, y: height / 2 };
    
    // Create the SVG element
    const svg = d3.select("#" + containerId)
        .append("svg")
        .attr("width", width)
        .attr("height", height)
        .attr("class", "ontology-diagram");
    
    // Add zoom functionality
    const zoom = d3.zoom()
        .scaleExtent([0.1, 3])
        .on("zoom", (event) => {
            g.attr("transform", event.transform);
        });
    
    svg.call(zoom);
    
    // Create a container for all elements with initial zoom
    const g = svg.append("g");
    
    // Create a force simulation
    const simulation = d3.forceSimulation()
        .force("link", d3.forceLink().id(d => d.id).distance(150))
        .force("charge", d3.forceManyBody().strength(-500))
        .force("center", d3.forceCenter(center.x, center.y))
        .force("collide", d3.forceCollide(70));
    
    // Process the data to create nodes and links
    const nodes = [];
    const links = [];
    
    console.log("Processing ontology data with classes:", ontologyData.classes.length);
    
    // Validate data and add default nodes if necessary
    if (!ontologyData.classes || ontologyData.classes.length === 0) {
        console.warn("No classes found in ontology data");
        // Add dummy data to prevent visualization from breaking
        nodes.push({
            id: "Thing",
            name: "Thing",
            type: "class",
            bfo: true
        });
    } else {
        // Add class nodes
        ontologyData.classes.forEach(cls => {
            if (!cls || !cls.id) {
                console.warn("Invalid class object in data");
                return; // Skip this iteration
            }
            
            nodes.push({
                id: cls.id,
                name: cls.name || cls.id,
                type: "class",
                bfo: cls.bfo || false
            });
        });
    }
    
    // Add inheritance links
    if (ontologyData.inheritance && Array.isArray(ontologyData.inheritance)) {
        ontologyData.inheritance.forEach(relation => {
            if (!relation || !relation.source || !relation.target) {
                console.warn("Invalid inheritance relation:", relation);
                return; // Skip this iteration
            }
            
            // Verify that source and target exist in nodes
            const sourceExists = nodes.some(node => node.id === relation.source);
            const targetExists = nodes.some(node => node.id === relation.target);
            
            if (!sourceExists || !targetExists) {
                console.warn(`Skipping inheritance relation with missing nodes: ${relation.source} -> ${relation.target}`);
                return;
            }
            
            links.push({
                source: relation.source,
                target: relation.target,
                type: relation.type || "inheritance"
            });
        });
    }
    
    // Add property relationships
    if (ontologyData.properties && Array.isArray(ontologyData.properties)) {
        ontologyData.properties.forEach(prop => {
            if (!prop || !prop.source || !prop.target) {
                console.warn("Invalid property relation:", prop);
                return; // Skip this iteration
            }
            
            // Verify that source and target exist in nodes
            const sourceExists = nodes.some(node => node.id === prop.source);
            const targetExists = nodes.some(node => node.id === prop.target);
            
            if (!sourceExists || !targetExists) {
                console.warn(`Skipping property relation with missing nodes: ${prop.source} -> ${prop.target}`);
                return;
            }
            
            links.push({
                source: prop.source,
                target: prop.target,
                type: prop.type || "property",
                name: prop.label || prop.name || "has_relation"
            });
        });
    }
    
    console.log("Processed nodes:", nodes.length, "links:", links.length);
    
    // Create the link elements
    const link = g.append("g")
        .attr("class", "links")
        .selectAll("g")
        .data(links)
        .enter()
        .append("g");
    
    // Add lines for links
    const linkLine = link.append("line")
        .attr("class", d => "link " + d.type)
        .attr("marker-end", d => d.type === "inheritance" ? "url(#inheritance-arrow)" : "url(#property-arrow)");
    
    // Add labels for property links
    const linkText = link.filter(d => d.type === "property")
        .append("text")
        .attr("class", "link-label")
        .attr("text-anchor", "middle")
        .attr("dy", -5)
        .text(d => d.name);
    
    // Create the node elements
    const node = g.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(nodes)
        .enter()
        .append("g")
        .attr("class", "node")
        .call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended));
    
    // Add rectangles for class nodes
    node.append("rect")
        .attr("class", d => "node-shape " + (d.bfo ? "bfo-class" : "domain-class"))
        .attr("width", d => Math.max(100, d.name.length * 8))
        .attr("height", 40)
        .attr("rx", 5)
        .attr("ry", 5)
        .attr("x", d => -(Math.max(100, d.name.length * 8)) / 2)
        .attr("y", -20);
    
    // Add labels for nodes
    node.append("text")
        .attr("class", "node-label")
        .attr("text-anchor", "middle")
        .attr("dy", 5)
        .text(d => d.name);
    
    // Add arrow markers for links
    svg.append("defs").selectAll("marker")
        .data(["inheritance-arrow", "property-arrow"])
        .enter().append("marker")
        .attr("id", d => d)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 25)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("class", d => d);
    
    // Update the simulation
    simulation
        .nodes(nodes)
        .on("tick", ticked);
    
    simulation.force("link")
        .links(links);
    
    // Add legend
    const legend = svg.append("g")
        .attr("class", "legend")
        .attr("transform", "translate(20, 20)");
    
    const legendItems = [
        { label: "Domain Class", class: "domain-class" },
        { label: "BFO Class", class: "bfo-class" },
        { label: "Inheritance", class: "inheritance" },
        { label: "Property", class: "property" }
    ];
    
    const legendSpacing = 25;
    
    legendItems.forEach((item, i) => {
        const g = legend.append("g")
            .attr("transform", `translate(0, ${i * legendSpacing})`);
        
        if (item.class === "domain-class" || item.class === "bfo-class") {
            g.append("rect")
                .attr("width", 20)
                .attr("height", 20)
                .attr("rx", 3)
                .attr("ry", 3)
                .attr("class", "node-shape " + item.class);
        } else {
            g.append("line")
                .attr("x1", 0)
                .attr("y1", 10)
                .attr("x2", 20)
                .attr("y2", 10)
                .attr("class", "link " + item.class);
        }
        
        g.append("text")
            .attr("x", 30)
            .attr("y", 15)
            .text(item.label);
    });
    
    // Functions for handling the simulation ticks and dragging
    function ticked() {
        linkLine
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);
        
        linkText
            .attr("x", d => (d.source.x + d.target.x) / 2)
            .attr("y", d => (d.source.y + d.target.y) / 2);
        
        node
            .attr("transform", d => `translate(${d.x}, ${d.y})`);
    }
    
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }
    
    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }
    
    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
    
    // Add some controls for the visualization
    const controls = d3.select("#" + containerId)
        .append("div")
        .attr("class", "visualization-controls");
    
    controls.append("button")
        .attr("class", "btn btn-sm btn-secondary me-2")
        .text("Reset View")
        .on("click", () => {
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity
            );
        });
    
    controls.append("button")
        .attr("class", "btn btn-sm btn-secondary me-2")
        .text("Zoom In")
        .on("click", () => {
            svg.transition().duration(300).call(
                zoom.scaleBy,
                1.2
            );
        });
    
    controls.append("button")
        .attr("class", "btn btn-sm btn-secondary me-2")
        .text("Zoom Out")
        .on("click", () => {
            svg.transition().duration(300).call(
                zoom.scaleBy,
                0.8
            );
        });
    
    return {
        svg: svg,
        simulation: simulation
    };
}