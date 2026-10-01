import {
  AmbientLight, CapsuleGeometry, CatmullRomCurve3, Color, DirectionalLight,
  Group, Mesh, MeshStandardMaterial, OrthographicCamera, Scene, SphereGeometry,
  SRGBColorSpace, TorusGeometry, TubeGeometry, Vector3, WebGLRenderer,
  type BufferGeometry,
} from 'three';

/** Small, procedural model: no remote model, textures, or animation services. */
export function createWelcomeCharacter(canvas: HTMLCanvasElement) {
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.setClearColor(0xffffff, 0);
  const scene = new Scene();
  const camera = new OrthographicCamera(-1.8, 1.8, 2.1, -2.1, 0.1, 30);
  camera.position.set(0, 1.75, 9);
  camera.lookAt(0, 1.75, 0);
  scene.add(new AmbientLight(0xffffff, 2));
  const key = new DirectionalLight(0xffffff, 3.2);
  key.position.set(-3, 6, 5);
  scene.add(key);
  const rim = new DirectionalLight(0xe3e8f3, 2);
  rim.position.set(4, 3, -2);
  scene.add(rim);

  const skin = new MeshStandardMaterial({ color: new Color('#eeeae5'), roughness: 0.75 });
  const black = new MeshStandardMaterial({ color: '#141416', roughness: 0.65 });
  const hair = new MeshStandardMaterial({ color: '#101012', roughness: 0.48 });
  const white = new MeshStandardMaterial({ color: '#ffffff', roughness: 0.4 });
  const geometries: BufferGeometry[] = [];
  const model = new Group();
  scene.add(model);
  function mesh(parent: Group, geometry: BufferGeometry, material: MeshStandardMaterial, x: number, y: number, z: number) {
    geometries.push(geometry);
    const object = new Mesh(geometry, material);
    object.position.set(x, y, z);
    parent.add(object);
    return object;
  }
  function sphere(parent: Group, material: MeshStandardMaterial, position: number[], scale: number[]) {
    const object = mesh(parent, new SphereGeometry(1, 24, 20), material, position[0]!, position[1]!, position[2]!);
    object.scale.set(scale[0]!, scale[1]!, scale[2]!);
    return object;
  }
  function limb(parent: Group, start: number[], end: number[], radius: number, material: MeshStandardMaterial) {
    const a = new Vector3(...start as [number, number, number]);
    const b = new Vector3(...end as [number, number, number]);
    const midpoint = a.clone().add(b).multiplyScalar(0.5);
    const object = mesh(parent, new CapsuleGeometry(radius, a.distanceTo(b), 5, 12), material, midpoint.x, midpoint.y, midpoint.z);
    object.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), b.sub(a).normalize());
    return object;
  }
  function curve(parent: Group, points: number[][], radius: number, material: MeshStandardMaterial) {
    return mesh(parent, new TubeGeometry(new CatmullRomCurve3(points.map(point => new Vector3(...point as [number, number, number]))), 20, radius, 8, false), material, 0, 0, 0);
  }

  // Shirt, shoulders, and neck.
  sphere(model, black, [0.48, 0.48, 0], [0.87, 1.02, 0.43]);
  limb(model, [1.1, 1.0, 0], [1.25, 0.15, 0.05], 0.22, black);
  limb(model, [0.48, 1.3, 0], [0.48, 1.94, 0], 0.17, skin);
  sphere(model, black, [0.48, 1.37, 0], [0.25, 0.075, 0.24]);

  const head = new Group();
  head.position.set(0.48, 2.43, 0);
  model.add(head);
  sphere(head, skin, [0, 0, 0], [0.59, 0.74, 0.44]);
  sphere(head, skin, [-0.57, -0.01, 0], [0.12, 0.17, 0.1]);
  sphere(head, skin, [0.57, -0.01, 0], [0.12, 0.17, 0.1]);
  sphere(head, skin, [0, -0.12, 0.44], [0.10, 0.12, 0.13]);

  // Sculpted swept hair, using overlapping smooth volumes.
  sphere(head, hair, [0, 0.55, -0.09], [0.6, 0.32, 0.43]);
  const quiff = sphere(head, hair, [0.10, 0.68, 0.08], [0.58, 0.26, 0.39]);
  quiff.rotation.z = 0.19;
  sphere(head, hair, [-0.42, 0.52, 0.10], [0.22, 0.25, 0.32]);
  sphere(head, hair, [0.44, 0.72, 0], [0.20, 0.23, 0.28]);

  const eyes = new Group();
  head.add(eyes);
  for (const x of [-0.25, 0.25]) {
    sphere(eyes, white, [x, 0.10, 0.385], [0.19, 0.20, 0.075]);
    sphere(eyes, black, [x + 0.01, 0.10, 0.461], [0.055, 0.075, 0.028]);
    sphere(eyes, white, [x - 0.003, 0.13, 0.486], [0.015, 0.019, 0.008]);
    mesh(head, new TorusGeometry(0.225, 0.023, 8, 36), black, x, 0.10, 0.455);
    curve(head, [[x - 0.13, 0.39, 0.37], [x, 0.43, 0.40], [x + 0.11, 0.40, 0.37]], 0.021, hair);
  }
  curve(head, [[-0.04, 0.12, 0.46], [0, 0.15, 0.48], [0.04, 0.12, 0.46]], 0.022, black);
  limb(head, [-0.47, 0.13, 0.44], [-0.57, 0.12, 0.02], 0.024, black);
  limb(head, [0.47, 0.13, 0.44], [0.57, 0.12, 0.02], 0.024, black);
  curve(head, [[-0.16, -0.34, 0.40], [0, -0.40, 0.43], [0.16, -0.34, 0.40]], 0.022, black);

  // Waving arm hinges at the elbow; fingers and thumb are separate volumes.
  limb(model, [-0.18, 1.07, 0], [-0.87, 0.63, 0.06], 0.21, black);
  const arm = new Group();
  arm.position.set(-0.89, 0.60, 0.1);
  arm.rotation.z = 0.24;
  model.add(arm);
  limb(arm, [0, 0, 0], [0, 1.03, 0], 0.105, skin);
  const hand = new Group();
  hand.position.set(0, 1.23, 0);
  arm.add(hand);
  sphere(hand, skin, [0, 0.03, 0], [0.19, 0.25, 0.085]);
  for (const [x, length, spread] of [[-0.14, 0.31, -0.09], [-0.05, 0.43, -0.025], [0.05, 0.40, 0.025], [0.14, 0.29, 0.07]]) {
    limb(hand, [x!, 0.17, 0], [x! + spread!, 0.17 + length!, 0], 0.042, skin);
  }
  limb(hand, [0.14, -0.04, 0], [0.31, 0.16, 0.035], 0.065, skin);

  let running = false;
  let elapsed = 0;
  let previous = 0;
  let targetX = 0;
  let targetY = 0;
  let disposed = false;
  function draw() { renderer.render(scene, camera); }
  function animate(now: number) {
    elapsed += previous ? Math.min((now - previous) / 1000, 0.05) : 0;
    previous = now;
    // A brief wave followed by a relaxed hold avoids constant frantic motion.
    const cycle = elapsed % 6;
    const wave = cycle < 2.6 ? Math.sin(cycle / 2.6 * Math.PI) * Math.sin(cycle * 8) : 0;
    arm.rotation.z = 0.24 + wave * 0.20;
    hand.rotation.z = wave * 0.16;
    model.position.y = Math.sin(elapsed * 1.6) * 0.025;
    model.rotation.y += (targetX * 0.18 + Math.sin(elapsed * 0.65) * 0.06 - model.rotation.y) * 0.045;
    head.rotation.y += (targetX * 0.12 - head.rotation.y) * 0.07;
    head.rotation.x += (targetY * 0.07 + Math.sin(elapsed * 1.1) * 0.025 - head.rotation.x) * 0.07;
    const blink = elapsed % 4.7;
    eyes.scale.y = blink > 4.48 ? Math.max(0.08, Math.abs(blink - 4.59) / 0.11) : 1;
    draw();
  }
  return {
    resize(width: number, height: number) {
      if (disposed || !width || !height) return;
      const halfWidth = 2.1 * width / height;
      camera.left = -halfWidth; camera.right = halfWidth;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      draw();
    },
    point(x: number, y: number) { targetX = x; targetY = y; },
    play(value: boolean) {
      if (disposed || running === value) return;
      running = value;
      previous = 0;
      renderer.setAnimationLoop(value ? animate : null);
      if (!value) draw();
    },
    dispose() {
      disposed = true;
      renderer.setAnimationLoop(null);
      geometries.forEach(geometry => geometry.dispose());
      [skin, black, hair, white].forEach(material => material.dispose());
      renderer.dispose();
    },
  };
}
