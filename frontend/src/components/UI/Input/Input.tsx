import styles from "./Input.module.css";

interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> {}

function Input(props: InputProps) {
    return (
        <input
            className={styles.input}
            {...props}
        />
    );
}

export default Input;