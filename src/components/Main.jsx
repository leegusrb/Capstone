//jsx의 주의사항
//1. 중과호 내부에는 자바스크립트 표현식만 넣을 수 있음 즉 조건문이나 반복문 x
//2. 숫자,문자열,배열 값만 렌더링된다. true,undefined,null은 렌더링 x객체도 렌더링 그대로 x 점표기버을 이용해서 문자나 숫자 렌더링해야됨
//3. 모든 태그는 닫혀있어야 한다 즉 <h1> </h1>으로 받는걸 해야됨
//4. 최상위 태그는 반드시 하나여야만 한다. ex)<main>으로 하나만 묶어야됨

// const Main = ()=>{
//     const number = 10;

//     return ( 
//     <main>
//         <h1>main</h1>
//         <h2>{number+10==0?"짝수":"홀수"}</h2> 
//     </main>
//     );
// };
import "./Main.css";

export default Main;

const Main = () =>{
    const user = {
        name:"이정환",
        isLogin:true,
    };
///class가 아니라 className으로 해야함 자바랑 겹쳐서
    if (user.isLogin){
        return <div className = "logout"> 
        로그아웃</div>;
    } else {
        return <div>로그인</div>
    }

    // return (
    //     <>
    //         {user.isLogin ? (
    //             <div>로그아웃</div>
    //         ) :(
    //             <div>로그인</div>
    //         )}
    //     </>
    // );
};