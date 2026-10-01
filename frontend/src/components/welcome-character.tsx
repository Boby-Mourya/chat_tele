import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import './welcome-character.css';

type Character = ReturnType<typeof import('./welcome-character-scene').createWelcomeCharacter>;

export function WelcomeCharacter() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const character = useRef<Character | null>(null);
  const [ready, setReady] = useState(false);
  const [paused, setPaused] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
  const pausedRef = useRef(paused);
  const updatePlayback = useRef<() => void>(() => {});

  useEffect(() => {
    const element = canvas.current;
    if (!element || !window.WebGL2RenderingContext || !window.IntersectionObserver || !window.ResizeObserver) return;
    let active = true;
    let visible = true;
    let instance: Character | undefined;
    let resizeObserver: ResizeObserver | undefined;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => instance?.play(!pausedRef.current && visible && !document.hidden);
    updatePlayback.current = sync;
    const motionChanged = () => { pausedRef.current = motion.matches; setPaused(motion.matches); sync(); };
    const observer = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; sync(); });
    observer.observe(element);
    document.addEventListener('visibilitychange', sync);
    motion.addEventListener('change', motionChanged);
    const contextLost = () => { instance?.dispose(); instance = undefined; character.current = null; setReady(false); };
    element.addEventListener('webglcontextlost', contextLost);
    void import('./welcome-character-scene').then(({ createWelcomeCharacter }) => {
      if (!active) return;
      instance = createWelcomeCharacter(element);
      character.current = instance;
      const resize = () => instance?.resize(element.clientWidth, element.clientHeight);
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(element);
      resize();
      setReady(true);
      sync();
    }).catch(() => { if (active) setReady(false); });
    return () => {
      active = false;
      observer.disconnect();
      resizeObserver?.disconnect();
      document.removeEventListener('visibilitychange', sync);
      motion.removeEventListener('change', motionChanged);
      element.removeEventListener('webglcontextlost', contextLost);
      instance?.dispose();
      character.current = null;
    };
  }, []);

  return <span className={`welcome-character ${ready ? 'welcome-character--ready' : ''}`} onPointerMove={event => {
    if (pausedRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    character.current?.point(((event.clientX - rect.left) / rect.width - 0.5) * 2, ((event.clientY - rect.top) / rect.height - 0.5) * 2);
  }} onPointerLeave={() => character.current?.point(0, 0)}>
    <img className="welcome-character__fallback" src="/design/online-courses/welcome-illustration.png" alt="" width="181" height="195" />
    <canvas ref={canvas} className="welcome-character__canvas" aria-hidden="true" />
    {ready ? <button className="welcome-character__control" type="button" aria-label={paused ? 'Play character animation' : 'Pause character animation'} title={paused ? 'Play animation' : 'Pause animation'} onClick={() => {
      pausedRef.current = !pausedRef.current;
      setPaused(pausedRef.current);
      updatePlayback.current();
    }}>{paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}</button> : null}
  </span>;
}
